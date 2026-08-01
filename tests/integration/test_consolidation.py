"""End-to-end consolidation tests against a live CockroachDB."""

from __future__ import annotations

from uuid import UUID

import pytest

from retrace.memory import MemoryEngine
from retrace.memory.models import Evidence, EvidenceKind, IncidentStatus

pytestmark = pytest.mark.integration


def _resolved_incident(engine: MemoryEngine, org: str) -> UUID:
    iid: UUID = engine.incidents.create(org, "payments-api 5xx", "payments-api")["id"]
    engine.evidence.record(
        Evidence(
            org_id=org, incident_id=iid, kind=EvidenceKind.metric, content="error rate 5%, pool 94%"
        )
    )
    engine.evidence.record(
        Evidence(
            org_id=org,
            incident_id=iid,
            kind=EvidenceKind.deploy,
            content="deploy v2.4.1 six minutes before",
        )
    )
    hypothesis = engine.beliefs.create_hypothesis(org, iid, "deploy v2.4.1 connection leak")
    assert hypothesis.id is not None
    engine.beliefs.set_belief(org, iid, hypothesis.id, 0.9)
    engine.incidents.set_status(
        iid, IncidentStatus.resolved, resolution="rolled back v2.4.1 and raised the pool limit"
    )
    return iid


def test_consolidation_is_gated_on_resolution(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "still open", "svc")["id"]
    report = engine.consolidator.consolidate_incident(org, iid)
    assert report.skipped is True
    assert report.facts_created == 0


def test_consolidation_learns_facts_and_procedure(engine: MemoryEngine, org: str) -> None:
    iid = _resolved_incident(engine, org)
    report = engine.consolidator.consolidate_incident(org, iid)

    assert report.skipped is False
    assert report.facts_created >= 1
    assert report.procedure_created is True

    assert engine.semantic.recall(org, "payments deploy connection leak", top_k=5)

    procedures = engine.procedural.recall(org, "deploy v2.4.1 connection leak", top_k=5)
    assert procedures
    assert "rolled back" in procedures[0].steps

    # Evidence is untouched and the ledger chain still verifies.
    assert len(engine.evidence.for_incident(iid)) == 2
    assert engine.ledger.verify(iid) is True


def test_consolidation_reinforces_instead_of_duplicating(engine: MemoryEngine, org: str) -> None:
    iid = _resolved_incident(engine, org)
    engine.consolidator.consolidate_incident(org, iid)
    second = engine.consolidator.consolidate_incident(org, iid)

    assert second.facts_created == 0
    assert second.facts_reinforced >= 1
    assert second.procedure_reinforced is True


def test_decay_updates_retrieval_scores_idempotently(engine: MemoryEngine, org: str) -> None:
    iid = _resolved_incident(engine, org)
    engine.consolidator.consolidate_incident(org, iid)
    counts = engine.consolidator.decay(org)
    assert counts["semantic"] >= 1
    # A second decay must not error and remains well-defined (idempotent).
    engine.consolidator.decay(org)
