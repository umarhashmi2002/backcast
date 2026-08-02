"""Evidence-preserving consolidation (the reflection loop).

Runs only on a *resolved/closed* incident (gated — not after every turn). It reads
the incident's immutable evidence and the agent's final beliefs, distills reusable
semantic facts and (if a remediation worked) a procedure, and links them back to the
evidence they came from via provenance edges. It NEVER mutates or deletes evidence;
duplicates are reinforced rather than re-created, and staleness is handled by decay.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol
from uuid import UUID

from ..telemetry import get_logger
from .models import ConsolidationReport, NodeType, Relation

if TYPE_CHECKING:
    from .engine import MemoryEngine

log = get_logger(__name__)

_RESOLVED_STATES = {"resolved", "closed"}


@dataclass
class DistilledFact:
    statement: str
    confidence: float = 0.7


@dataclass
class DistilledProcedure:
    name: str
    trigger_pattern: str
    steps: str


@dataclass
class DistillationResult:
    facts: list[DistilledFact] = field(default_factory=list)
    procedure: DistilledProcedure | None = None


class Distiller(Protocol):
    def distill(
        self,
        *,
        service: str,
        top_hypothesis: str,
        evidence_texts: Sequence[str],
        resolution: str | None,
    ) -> DistillationResult: ...


class RuleBasedDistiller:
    """Deterministic distiller — no LLM required (used for offline/CI and as a fallback)."""

    def distill(
        self,
        *,
        service: str,
        top_hypothesis: str,
        evidence_texts: Sequence[str],
        resolution: str | None,
    ) -> DistillationResult:
        facts: list[DistilledFact] = []
        if top_hypothesis:
            facts.append(
                DistilledFact(
                    f"For service '{service}', watch for this failure mode: {top_hypothesis}.", 0.7
                )
            )
        if resolution:
            facts.append(
                DistilledFact(
                    f"'{service}' incidents like this were resolved by: {resolution}", 0.75
                )
            )
        procedure: DistilledProcedure | None = None
        trigger = top_hypothesis or (evidence_texts[0] if evidence_texts else "")
        if resolution and trigger:
            procedure = DistilledProcedure(
                name=f"Remediate {service}", trigger_pattern=trigger, steps=resolution
            )
        return DistillationResult(facts=facts, procedure=procedure)


_DISTILL_SYSTEM = (
    "You distill a resolved incident into reusable operational knowledge. "
    "Respond ONLY with JSON of the form "
    '{"facts": [{"statement": str, "confidence": number}], '
    '"procedure": {"name": str, "trigger_pattern": str, "steps": str} | null}. '
    "Facts must be generally reusable, not specific to this one incident id."
)


class LLMDistiller:
    """Distills via a text-completion callable (system, prompt) -> str returning JSON."""

    def __init__(self, complete: Callable[[str, str], str]) -> None:
        self._complete = complete

    def distill(
        self,
        *,
        service: str,
        top_hypothesis: str,
        evidence_texts: Sequence[str],
        resolution: str | None,
    ) -> DistillationResult:
        prompt = (
            f"Service: {service}\n"
            f"Most-supported root cause: {top_hypothesis or 'unknown'}\n"
            f"Resolution: {resolution or 'none recorded'}\n"
            f"Evidence:\n- " + "\n- ".join(evidence_texts[:20])
        )
        raw = self._complete(_DISTILL_SYSTEM, prompt)
        data = _extract_json(raw)
        facts = [
            DistilledFact(str(f["statement"]), float(f.get("confidence", 0.7)))
            for f in data.get("facts", [])
            if isinstance(f, dict) and f.get("statement")
        ]
        procedure = None
        proc = data.get("procedure")
        if isinstance(proc, dict) and proc.get("steps"):
            procedure = DistilledProcedure(
                name=str(proc.get("name", f"Remediate {service}")),
                trigger_pattern=str(proc.get("trigger_pattern", top_hypothesis)),
                steps=str(proc["steps"]),
            )
        return DistillationResult(facts=facts, procedure=procedure)


def _extract_json(text: str) -> dict[str, Any]:
    """Parse the first JSON object in a model response, tolerating prose/fences."""
    try:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        parsed = json.loads(match.group(0) if match else text)
        return parsed if isinstance(parsed, dict) else {}
    except (json.JSONDecodeError, ValueError):
        log.warning("distill.parse_failed")
        return {}


class Consolidator:
    def __init__(self, engine: MemoryEngine, distiller: Distiller | None = None) -> None:
        self._engine = engine
        self._distiller = distiller or RuleBasedDistiller()

    def consolidate_incident(self, org_id: str, incident_id: UUID | str) -> ConsolidationReport:
        engine = self._engine
        iid = UUID(str(incident_id))
        incident = engine.incidents.get(incident_id)
        if incident is None:
            raise ValueError(f"unknown incident: {incident_id}")

        report = ConsolidationReport(incident_id=iid)
        if str(incident["status"]) not in _RESOLVED_STATES:
            report.skipped = True
            report.reason = f"incident not resolved (status={incident['status']})"
            return report

        evidence = engine.evidence.for_incident(incident_id)
        beliefs = engine.beliefs.current_beliefs(incident_id)
        top_hypothesis = ""
        if beliefs:
            hyp = engine.conn.execute(
                "SELECT statement FROM hypotheses WHERE id = %s", (beliefs[0].hypothesis_id,)
            ).fetchone()
            top_hypothesis = str(hyp["statement"]) if hyp else ""

        service = str(incident["service"])
        resolution = incident.get("resolution")
        distilled = self._distiller.distill(
            service=service,
            top_hypothesis=top_hypothesis,
            evidence_texts=[e.content for e in evidence],
            resolution=str(resolution) if resolution else None,
        )

        evidence_ids = [e.id for e in evidence if e.id is not None]
        for fact in distilled.facts:
            embedding = engine.embedder.embed_one(fact.statement)
            existing = engine.semantic.find_similar(org_id, embedding)
            if existing is not None:
                engine.semantic.touch(existing.id)
                report.facts_reinforced += 1
                continue
            created = engine.semantic.add(
                org_id,
                fact.statement,
                source="consolidation",
                service=service,
                confidence=fact.confidence,
                embedding=embedding,
            )
            assert created.id is not None
            for ev_id in evidence_ids:
                engine.beliefs.add_edge(
                    org_id,
                    incident_id,
                    NodeType.semantic_fact,
                    created.id,
                    Relation.derived_from,
                    NodeType.evidence,
                    ev_id,
                )
            engine.ledger.append(
                org_id,
                incident_id,
                "fact_learned",
                {"fact_id": str(created.id), "statement": fact.statement},
                actor="consolidator",
            )
            report.facts_created += 1

        if distilled.procedure is not None:
            embedding = engine.embedder.embed_one(distilled.procedure.trigger_pattern)
            existing_proc = engine.procedural.find_similar(org_id, embedding)
            if existing_proc is not None:
                engine.procedural.record_outcome(existing_proc.id, success=True)
                report.procedure_reinforced = True
            else:
                proc = engine.procedural.add(
                    org_id,
                    distilled.procedure.name,
                    distilled.procedure.trigger_pattern,
                    distilled.procedure.steps,
                    service=service,
                    source_incident_id=iid,
                    embedding=embedding,
                )
                assert proc.id is not None
                engine.beliefs.add_edge(
                    org_id,
                    incident_id,
                    NodeType.procedure,
                    proc.id,
                    Relation.remediates,
                    NodeType.incident,
                    iid,
                )
                engine.ledger.append(
                    org_id,
                    incident_id,
                    "procedure_learned",
                    {"procedure_id": str(proc.id), "name": distilled.procedure.name},
                    actor="consolidator",
                )
                report.procedure_created = True

        log.info(
            "consolidate.done",
            incident_id=str(iid),
            facts_created=report.facts_created,
            facts_reinforced=report.facts_reinforced,
            procedure_created=report.procedure_created,
        )
        return report

    def decay(self, org_id: str) -> dict[str, int]:
        """Maintenance pass: recompute retrieval scores for long-term memory."""
        return {
            "semantic": self._engine.semantic.decay(org_id),
            "procedural": self._engine.procedural.decay(org_id),
        }
