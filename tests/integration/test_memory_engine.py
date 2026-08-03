"""End-to-end tests of the memory engine against a live CockroachDB.

These mirror the four headline mechanisms through the Python engine:
temporal no-leak reconstruction, belief revision, the hash-chained ledger,
and transactional action leases — plus vector recall.
"""

from __future__ import annotations

import time

import pytest

from backcast.memory import MemoryEngine
from backcast.memory.models import Evidence, EvidenceKind

pytestmark = pytest.mark.integration


def _record(engine: MemoryEngine, org: str, iid: object, kind: EvidenceKind, content: str) -> None:
    engine.evidence.record(
        Evidence(org_id=org, incident_id=iid, kind=kind, content=content)  # type: ignore[arg-type]
    )


def test_temporal_reconstruction_has_no_leak(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "API 5xx spike", "payments-api")["id"]
    _record(engine, org, iid, EvidenceKind.metric, "API error rate climbing to five percent")
    hlc = engine.temporal.capture_hlc()
    _record(
        engine,
        org,
        iid,
        EvidenceKind.deploy,
        "Deploy v2.4.1 shipped six minutes before degradation",
    )

    now_state = engine.temporal.reconstruct(iid, engine.temporal.capture_hlc())
    assert len(now_state.evidence) == 2

    past = engine.temporal.reconstruct(iid, hlc)
    assert len(past.evidence) == 1
    assert past.evidence[0].kind == EvidenceKind.metric


def test_belief_revision_tracks_history(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "Outage", "payments-api")["id"]
    surge = engine.beliefs.create_hypothesis(org, iid, "Traffic surge")
    deploy = engine.beliefs.create_hypothesis(org, iid, "Deploy defect / connection leak")

    engine.beliefs.set_belief(org, iid, surge.id, 0.58, rationale="no deploy correlation yet")
    engine.beliefs.set_belief(org, iid, deploy.id, 0.11)
    # New evidence flips the conclusion.
    engine.beliefs.set_belief(org, iid, deploy.id, 0.87, rationale="deploy v2.4.1 correlated")
    engine.beliefs.set_belief(org, iid, surge.id, 0.08)

    current = {str(b.hypothesis_id): b.confidence for b in engine.beliefs.current_beliefs(iid)}
    assert current[str(deploy.id)] == pytest.approx(0.87)
    assert current[str(surge.id)] == pytest.approx(0.08)

    history = engine.beliefs.belief_history(iid, deploy.id)
    assert len(history) == 2
    assert history[0].valid_until is not None  # superseded
    assert history[-1].valid_until is None  # currently held


def test_ledger_hash_chain(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "Outage", "svc")["id"]
    e1 = engine.ledger.append(org, iid, "incident_opened", {"service": "svc"})
    e2 = engine.ledger.append(org, iid, "evidence_recorded", {"count": 1})

    assert (e1.seq, e2.seq) == (1, 2)
    assert e2.prev_hash == e1.entry_hash
    assert engine.ledger.verify(iid) is True


def test_action_lease_single_owner(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "Outage", "payments-api")["id"]
    key = "rollback:payments-api:v2.4.1"

    winners = [engine.leases.claim(org, iid, key, holder=f"worker-{w}") for w in range(5)]
    won = [c for c in winners if c.won]
    assert len(won) == 1

    lease = engine.leases.get(org, key)
    assert lease is not None
    assert lease["holder"] == won[0].holder


def test_action_lease_fencing_rejects_stale_holder(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "Outage", "payments-api")["id"]
    key = f"rollback:{iid}"

    first = engine.leases.claim(org, iid, key, holder="worker-A", ttl_seconds=1)
    assert first.won
    assert first.lease_id is not None
    time.sleep(1.2)  # let the lease expire

    taker = engine.leases.take_over_if_expired(org, key, holder="worker-B")
    assert taker is not None
    assert taker.lease_generation == first.lease_generation + 1

    # The revived original holder (stale generation) is fenced out; the taker succeeds.
    assert engine.leases.complete(first.lease_id, "worker-A", first.lease_generation) is False
    assert taker.lease_id is not None
    assert engine.leases.complete(taker.lease_id, "worker-B", taker.lease_generation) is True


def test_evidence_recall_ranks_relevant_first(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "Outage", "payments-api")["id"]
    _record(
        engine, org, iid, EvidenceKind.metric, "database connection pool saturated at maximum limit"
    )
    _record(engine, org, iid, EvidenceKind.log, "nightly cron job finished successfully")

    results = engine.evidence.recall(org, "database connection pool exhausted", top_k=2)
    assert results
    assert "connection pool" in results[0].content


def test_historical_recall_is_exact_and_leak_free(engine: MemoryEngine, org: str) -> None:
    iid1 = engine.incidents.create(org, "5xx", "payments-api")["id"]
    _record(engine, org, iid1, EvidenceKind.metric, "database connection pool saturated at limit")
    hlc = engine.temporal.capture_hlc()

    # Evidence recorded AFTER the captured HLC must not appear in the historical view.
    iid2 = engine.incidents.create(org, "later outage", "svc")["id"]
    _record(engine, org, iid2, EvidenceKind.log, "database connection pool saturated again later")

    results = engine.historical_recall(org, "connection pool saturated", hlc, top_k=5)
    contents = [r.content for r in results]
    assert any("at limit" in c for c in contents)  # the past evidence is recalled
    assert all("later" not in c for c in contents)  # the future evidence does not leak


def test_ledger_checkpoint_signs_and_detects_tampering(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "outage", "svc")["id"]
    engine.ledger.append(org, iid, "incident_opened", {"service": "svc"})
    engine.ledger.append(org, iid, "belief_updated", {"confidence": 0.9})

    checkpoint = engine.checkpointer.checkpoint(org, iid)
    assert checkpoint.seq_covered == 2
    assert engine.checkpointer.verify_latest(iid) is True

    # Tampering with an earlier ledger payload breaks chain verification.
    engine.conn.execute(
        "UPDATE event_ledger SET payload = '{\"service\":\"hacked\"}'::JSONB "
        "WHERE incident_id = %s AND seq = 1",
        (iid,),
    )
    assert engine.checkpointer.verify_latest(iid) is False
