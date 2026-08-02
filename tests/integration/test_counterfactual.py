"""End-to-end counterfactual replay against a live CockroachDB."""

from __future__ import annotations

import pytest

from backcast.memory import MemoryEngine
from backcast.memory.models import IncidentStatus

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


def test_counterfactual_requires_a_scenario(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "generic outage", "svc")["id"]  # no scenario attached
    with pytest.raises(ValueError, match="scenario"):
        engine.counterfactual.run(org, iid, actual_remediations=["restart-service"])
