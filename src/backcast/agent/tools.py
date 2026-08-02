"""Agent tools — the safe, typed surface the LLM may act through.

Every tool maps to a memory-engine operation and appends to the hash-chained
ledger, so the agent's actions are always recorded and auditable. Tools never
execute raw SQL from the model; inputs are validated and passed as parameters.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from ..memory import MemoryEngine
from ..memory.models import Evidence, EvidenceKind, IncidentStatus
from ..telemetry import get_logger
from .llm import ToolSpec

log = get_logger(__name__)

TOOL_SPECS: list[ToolSpec] = [
    ToolSpec(
        name="recall_similar_incidents",
        description=(
            "Semantic search over evidence from PAST incidents (excludes the current one). "
            "Use this first to see how similar symptoms were handled before."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Symptom description to search for."},
                "limit": {"type": "integer", "minimum": 1, "maximum": 10, "default": 5},
            },
            "required": ["query"],
        },
    ),
    ToolSpec(
        name="record_observation",
        description="Record a new piece of evidence you have observed for this incident.",
        input_schema={
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [k.value for k in EvidenceKind],
                    "description": "The type of signal.",
                },
                "content": {"type": "string"},
                "source": {"type": "string", "default": "agent"},
            },
            "required": ["kind", "content"],
        },
    ),
    ToolSpec(
        name="assess_hypothesis",
        description=(
            "State or update your confidence (0.0-1.0) that a hypothesis explains the incident. "
            "Calling again with the same hypothesis revises your belief and preserves the history."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "hypothesis": {"type": "string", "description": "The candidate root cause."},
                "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                "rationale": {"type": "string"},
            },
            "required": ["hypothesis", "confidence"],
        },
    ),
    ToolSpec(
        name="propose_remediation",
        description=(
            "Propose an action to remediate the incident. This attempts to CLAIM an exclusive "
            "action lease; only one worker may hold it. Only propose when sufficiently confident."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Short action slug, e.g. 'rollback-v2.4.1'.",
                },
                "rationale": {"type": "string"},
            },
            "required": ["action", "rationale"],
        },
    ),
    ToolSpec(
        name="resolve_incident",
        description="Mark the incident resolved with a short resolution summary.",
        input_schema={
            "type": "object",
            "properties": {"resolution": {"type": "string"}},
            "required": ["resolution"],
        },
    ),
]


class AgentTools:
    """Bound tool implementations for one incident-handling session."""

    def __init__(
        self,
        engine: MemoryEngine,
        org_id: str,
        incident_id: UUID | str,
        *,
        worker_id: str = "agent",
    ) -> None:
        self._engine = engine
        self._org = org_id
        self._incident_id = incident_id
        self._worker = worker_id
        self._handlers = {
            "recall_similar_incidents": self._recall_similar_incidents,
            "record_observation": self._record_observation,
            "assess_hypothesis": self._assess_hypothesis,
            "propose_remediation": self._propose_remediation,
            "resolve_incident": self._resolve_incident,
        }

    def dispatch(self, name: str, tool_input: dict[str, Any]) -> tuple[dict[str, Any], bool]:
        """Run a tool. Returns (result, is_error)."""
        handler = self._handlers.get(name)
        if handler is None:
            return {"error": f"unknown tool: {name}"}, True
        try:
            return handler(tool_input), False
        except Exception as exc:  # surface tool errors back to the model, don't crash the loop
            log.warning("tool.error", tool=name, error=str(exc))
            return {"error": str(exc)}, True

    # --- handlers ----------------------------------------------------------
    def _recall_similar_incidents(self, args: dict[str, Any]) -> dict[str, Any]:
        matches = self._engine.evidence.recall(
            self._org,
            str(args["query"]),
            top_k=int(args.get("limit", 5)),
            exclude_incident=self._incident_id,
        )
        return {
            "matches": [
                {
                    "content": m.content,
                    "incident_id": str(m.incident_id),
                    "kind": m.kind.value,
                    "score": round(m.score, 3),
                }
                for m in matches
            ]
        }

    def _record_observation(self, args: dict[str, Any]) -> dict[str, Any]:
        evidence = self._engine.evidence.record(
            Evidence(
                org_id=self._org,
                incident_id=UUID(str(self._incident_id)),
                kind=EvidenceKind(str(args["kind"])),
                source=str(args.get("source", "agent")),
                content=str(args["content"]),
            )
        )
        self._engine.ledger.append(
            self._org,
            self._incident_id,
            "evidence_recorded",
            {"evidence_id": str(evidence.id), "kind": str(args["kind"])},
            actor=self._worker,
        )
        return {"evidence_id": str(evidence.id)}

    def _assess_hypothesis(self, args: dict[str, Any]) -> dict[str, Any]:
        hypothesis = self._engine.beliefs.get_or_create_hypothesis(
            self._org, self._incident_id, str(args["hypothesis"])
        )
        assert hypothesis.id is not None
        incident = self._engine.incidents.get(self._incident_id)
        state_version = int(incident["state_version"]) if incident else None
        belief = self._engine.beliefs.set_belief(
            self._org,
            self._incident_id,
            hypothesis.id,
            float(args["confidence"]),
            rationale=args.get("rationale"),
            model_id=self._engine.settings.bedrock_model_id,
            incident_state_version=state_version,
            created_by=self._worker,
        )
        self._engine.ledger.append(
            self._org,
            self._incident_id,
            "belief_updated",
            {"hypothesis": str(args["hypothesis"]), "confidence": belief.confidence},
            actor=self._worker,
        )
        return {"ok": True, "confidence": belief.confidence}

    def _propose_remediation(self, args: dict[str, Any]) -> dict[str, Any]:
        action = str(args["action"])
        action_key = f"{action}:{self._incident_id}"
        claim = self._engine.leases.claim(
            self._org,
            self._incident_id,
            action_key,
            holder=self._worker,
            payload={"action": action, "rationale": str(args.get("rationale", ""))},
        )
        self._engine.ledger.append(
            self._org,
            self._incident_id,
            "action_claimed",
            {"action_key": action_key, "won": claim.won, "holder": claim.holder},
            actor=self._worker,
        )
        return {
            "claimed": claim.won,
            "action_key": action_key,
            "holder": claim.holder if claim.won else claim.existing_holder,
            "note": "You hold the lease; safe to execute."
            if claim.won
            else "Another worker owns this action.",
        }

    def _resolve_incident(self, args: dict[str, Any]) -> dict[str, Any]:
        result = self._engine.incidents.set_status(
            self._incident_id, IncidentStatus.resolved, resolution=str(args["resolution"])
        )
        self._engine.ledger.append(
            self._org,
            self._incident_id,
            "incident_resolved",
            {"resolution": str(args["resolution"])},
            actor=self._worker,
        )
        return {"ok": True, "status": result["status"]}
