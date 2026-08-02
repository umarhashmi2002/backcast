"""Unit tests for the deterministic incident model (no DB/AWS)."""

from __future__ import annotations

from backcast.simulation.model import DeterministicIncidentModel
from backcast.simulation.scenarios import get_scenario

MODEL = DeterministicIncidentModel()


def test_rollback_permanently_fixes_pool_exhaustion() -> None:
    outcome = MODEL.simulate(get_scenario("db_pool_exhaustion"), ["rollback-deploy"])
    assert outcome.recovered is True
    assert outcome.recurred is False
    assert outcome.unnecessary_actions == 0


def test_restart_only_relieves_and_recurs() -> None:
    outcome = MODEL.simulate(get_scenario("db_pool_exhaustion"), ["restart-service"])
    assert outcome.recovered is False
    assert outcome.recurred is True


def test_rollback_beats_restart_and_wait() -> None:
    scenario = get_scenario("db_pool_exhaustion")
    rollback = MODEL.simulate(scenario, ["rollback-deploy"])
    restart = MODEL.simulate(scenario, ["restart-service"])
    wait = MODEL.simulate(scenario, ["wait"])
    assert rollback.score > wait.score
    assert rollback.score > restart.score
    # A permanent fix must always outrank any non-recovering branch.
    assert rollback.recovered
    assert not restart.recovered
    assert not wait.recovered


def test_acting_after_resolution_counts_as_unnecessary() -> None:
    outcome = MODEL.simulate(
        get_scenario("db_pool_exhaustion"), ["rollback-deploy", "restart-service"]
    )
    assert outcome.recovered is True
    assert outcome.unnecessary_actions == 1  # the restart after the fix was wasted


def test_wrong_scenario_remediation_has_no_effect() -> None:
    # Rolling back a deploy does nothing for an expired certificate.
    outcome = MODEL.simulate(get_scenario("cert_expiry"), ["rollback-deploy"])
    assert outcome.recovered is False
    assert outcome.unnecessary_actions == 1
    rotate = MODEL.simulate(get_scenario("cert_expiry"), ["rotate-cert"])
    assert rotate.recovered is True
