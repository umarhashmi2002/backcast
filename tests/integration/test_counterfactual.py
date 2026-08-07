"""End-to-end counterfactual replay against a live CockroachDB."""

from __future__ import annotations

import pytest

from backcast.memory import MemoryEngine
from backcast.memory.models import Evidence, EvidenceKind, IncidentStatus

pytestmark = pytest.mark.integration


def test_counterfactual_ranks_forks_and_promotes_lesson(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(
        org, "payments-api 5xx", "payments-api", scenario="db_pool_exhaustion"
    )["id"]
    fork_hlc = engine.temporal.capture_hlc()
    engine.incidents.set_status(iid, IncidentStatus.resolved, resolution="restarted the service")

    report = engine.counterfactual.run(
        org, iid, actual_remediations=["restart-service"], forked_at_hlc=fork_hlc
    )

    # The permanent fix wins; the actual (restart) only relieved and recurs.
    assert report.best.label == "fork:rollback-deploy"
    assert report.best.outcome.recovered is True
    assert report.actual is not None
    assert report.actual.outcome.recovered is False
    assert report.actual.outcome.recurred is True
    assert report.decision_regret > 1.0
    assert report.lesson is not None

    # Persisted: one branch per candidate + the actual, outcomes, a run, a learned procedure.
    branch_count = engine.conn.execute(
        "SELECT count(*) AS n FROM incident_branches WHERE incident_id = %s", (iid,)
    ).fetchone()
    assert branch_count is not None
    assert int(branch_count["n"]) >= 5

    procedures = engine.procedural.recall(org, "connection pool saturated after a deploy", top_k=1)
    assert procedures
    assert "rollback-deploy" in procedures[0].steps

    assert engine.ledger.verify(iid) is True


def test_rewind_reconstructs_the_fork_point_without_leaking_the_future(
    engine: MemoryEngine, org: str
) -> None:
    """The fork must see the decision point, not the hindsight recorded after it."""
    iid = engine.incidents.create(
        org, "payments-api 5xx", "payments-api", scenario="db_pool_exhaustion"
    )["id"]
    engine.evidence.record(
        Evidence(
            org_id=org,
            incident_id=iid,
            kind=EvidenceKind.metric,
            content="error rate climbing; pool at 94%",
        )
    )
    hypothesis = engine.beliefs.create_hypothesis(org, iid, "connection pool exhausted")
    assert hypothesis.id is not None
    engine.beliefs.set_belief(org, iid, hypothesis.id, 0.42, rationale="at the decision point")

    fork_hlc = engine.temporal.capture_hlc()

    # Everything below happens *after* the fork point and must stay invisible to it.
    engine.evidence.record(
        Evidence(
            org_id=org,
            incident_id=iid,
            kind=EvidenceKind.deploy,
            content="POST-FORK: deploy v9 correlated with the degradation",
        )
    )
    engine.beliefs.set_belief(org, iid, hypothesis.id, 0.97, rationale="hindsight")
    engine.incidents.set_status(iid, IncidentStatus.resolved, resolution="restarted the service")

    report = engine.counterfactual.run(
        org, iid, actual_remediations=["restart-service"], forked_at_hlc=fork_hlc
    )

    state = report.forked_state
    assert state is not None, "a fork HLC was supplied, so the state must be reconstructed"
    assert state.as_of_hlc == fork_hlc

    contents = [e.content for e in state.evidence]
    assert any("pool at 94%" in c for c in contents)
    assert not any("POST-FORK" in c for c in contents), (
        "evidence recorded after the fork leaked into the reconstruction"
    )

    # The belief carries its decision-point confidence, not the revised one.
    assert [b.confidence for b in state.beliefs] == [0.42]

    # And the as-of read of the incident itself predates the resolution.
    at_fork = engine.incidents.get(iid, as_of_hlc=fork_hlc)
    assert at_fork is not None
    assert at_fork["resolution"] is None
    assert engine.incidents.get(iid)["resolution"] == "restarted the service"  # type: ignore[index]


def test_run_without_a_fork_point_has_no_reconstructed_state(
    engine: MemoryEngine, org: str
) -> None:
    iid = engine.incidents.create(org, "x", "svc", scenario="db_pool_exhaustion")["id"]
    report = engine.counterfactual.run(org, iid, actual_remediations=["restart-service"])
    assert report.forked_at_hlc is None
    assert report.forked_state is None


def test_counterfactual_requires_a_scenario(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "generic outage", "svc")["id"]  # no scenario attached
    with pytest.raises(ValueError, match="scenario"):
        engine.counterfactual.run(org, iid, actual_remediations=["restart-service"])
