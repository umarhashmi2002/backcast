"""Counterfactual service: fork an incident, simulate alternatives, compare, learn.

The LLM (elsewhere) may propose which alternatives to try, but outcomes here are
computed by the deterministic incident model — the simulator never lets a model
decide whether an action succeeded. Results (branches, outcomes, the comparison,
and the promoted lesson) are all persisted to CockroachDB.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from psycopg.types.json import Json

from ..memory.models import BeliefState
from ..telemetry import get_logger
from .comparator import BranchResult, Comparison, compare
from .model import DeterministicIncidentModel
from .scenarios import Scenario, get_scenario

if TYPE_CHECKING:
    from ..memory.engine import MemoryEngine

log = get_logger(__name__)


@dataclass
class SimulationReport:
    incident_id: UUID
    scenario: str
    forked_at_hlc: str | None
    branches: list[BranchResult]
    actual: BranchResult | None
    best: BranchResult
    decision_regret: float
    lesson: str | None
    run_id: UUID
    # What the agent actually knew at forked_at_hlc, reconstructed via AS OF SYSTEM
    # TIME. None when no fork point was supplied (nothing to rewind to).
    forked_state: BeliefState | None = None


class CounterfactualService:
    def __init__(
        self, engine: MemoryEngine, model: DeterministicIncidentModel | None = None
    ) -> None:
        self._engine = engine
        self._model = model or DeterministicIncidentModel()

    @staticmethod
    def default_candidates(scenario: Scenario) -> dict[str, list[str]]:
        """One single-remediation branch per candidate remediation in the scenario."""
        return {name: [name] for name in scenario.remediations}

    def simulate_branch(
        self,
        org_id: str,
        incident_id: UUID | str,
        label: str,
        remediations: Sequence[str],
        *,
        forked_at_hlc: str | None = None,
        is_actual: bool = False,
        scenario: Scenario | None = None,
    ) -> BranchResult:
        """Simulate and persist one branch.

        ``run`` uses the batched path below; this remains the single-branch entry
        point. Pass ``scenario`` to skip the incident lookup.
        """
        scenario = scenario or self._scenario_for(incident_id)
        outcome = self._model.simulate(scenario, remediations)
        rem = list(remediations)
        with self._engine.conn.transaction():
            branch = self._engine.conn.execute(
                "INSERT INTO incident_branches "
                "(org_id, incident_id, label, forked_at_hlc, remediations, is_actual) "
                "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id",
                (org_id, incident_id, label, forked_at_hlc, rem, is_actual),
            ).fetchone()
            assert branch is not None
            self._engine.conn.execute(
                "INSERT INTO branch_outcomes (branch_id, recovered, recurred, time_to_recovery_s, "
                "unnecessary_actions, risk, cost, score, detail) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    branch["id"],
                    outcome.recovered,
                    outcome.recurred,
                    outcome.time_to_recovery_s,
                    outcome.unnecessary_actions,
                    outcome.risk,
                    outcome.cost,
                    outcome.score,
                    Json(outcome.as_dict()),
                ),
            )
        self._engine.ledger.append(
            org_id,
            incident_id,
            "branch_simulated",
            {
                "label": label,
                "remediations": rem,
                "score": outcome.score,
                "recovered": outcome.recovered,
            },
            actor="counterfactual",
        )
        return BranchResult(
            branch_id=branch["id"],
            label=label,
            remediations=rem,
            is_actual=is_actual,
            outcome=outcome,
        )

    def run(
        self,
        org_id: str,
        incident_id: UUID | str,
        actual_remediations: Sequence[str],
        *,
        candidates: Mapping[str, Sequence[str]] | None = None,
        forked_at_hlc: str | None = None,
    ) -> SimulationReport:
        """Rewind to the fork point, simulate the actual choice + alternatives, compare, learn.

        When ``forked_at_hlc`` is given this is a genuine rewind: the incident is
        read through ``AS OF SYSTEM TIME`` at that HLC, and the belief/evidence
        state as of that instant is reconstructed and returned on the report. The
        fork therefore derives from what was known at the decision point, and
        anything recorded afterwards is invisible to it by MVCC — including the
        resolution written when the incident was closed.
        """
        scenario = self._scenario_for(incident_id, as_of_hlc=forked_at_hlc)
        forked_state = (
            self._engine.temporal.reconstruct(incident_id, forked_at_hlc)
            if forked_at_hlc is not None
            else None
        )
        candidate_sets = candidates or self.default_candidates(scenario)

        specs: list[tuple[str, list[str], bool]] = [
            ("actual", list(actual_remediations), True),
            *((f"fork:{label}", list(rem), False) for label, rem in candidate_sets.items()),
        ]
        branches = self._simulate_batch(
            org_id, incident_id, scenario, specs, forked_at_hlc=forked_at_hlc
        )
        actual = branches[0]

        comparison = compare(branches)
        lesson: str | None = None
        if comparison.best.branch_id != actual.branch_id and comparison.best.outcome.recovered:
            lesson = self._promote_lesson(org_id, incident_id, scenario, comparison.best)

        run_id = self._persist_run(org_id, incident_id, scenario, forked_at_hlc, comparison, lesson)
        return SimulationReport(
            incident_id=UUID(str(incident_id)),
            scenario=scenario.key,
            forked_at_hlc=forked_at_hlc,
            branches=branches,
            actual=actual,
            best=comparison.best,
            decision_regret=comparison.decision_regret,
            lesson=lesson,
            run_id=run_id,
            forked_state=forked_state,
        )

    # --- internals ---------------------------------------------------------
    def _simulate_batch(
        self,
        org_id: str,
        incident_id: UUID | str,
        scenario: Scenario,
        specs: Sequence[tuple[str, list[str], bool]],
        *,
        forked_at_hlc: str | None,
    ) -> list[BranchResult]:
        """Simulate and persist every branch in one transaction plus one ledger append.

        Semantically identical to calling :meth:`simulate_branch` per spec, but it
        costs a fixed handful of round trips instead of four per branch. Outcomes
        are pure functions of the scenario, so they are all computed in memory
        first; branch ids are generated client-side so the two multi-row INSERTs
        need no ``RETURNING`` ordering guarantee.
        """
        outcomes = [(label, rem, is_actual) for label, rem, is_actual in specs]
        results: list[BranchResult] = []
        branch_rows: list[tuple[Any, ...]] = []
        outcome_rows: list[tuple[Any, ...]] = []

        for label, rem, is_actual in outcomes:
            branch_id = uuid4()
            outcome = self._model.simulate(scenario, rem)
            branch_rows.append(
                (branch_id, org_id, incident_id, label, forked_at_hlc, rem, is_actual)
            )
            outcome_rows.append(
                (
                    branch_id,
                    outcome.recovered,
                    outcome.recurred,
                    outcome.time_to_recovery_s,
                    outcome.unnecessary_actions,
                    outcome.risk,
                    outcome.cost,
                    outcome.score,
                    Json(outcome.as_dict()),
                )
            )
            results.append(
                BranchResult(
                    branch_id=branch_id,
                    label=label,
                    remediations=rem,
                    is_actual=is_actual,
                    outcome=outcome,
                )
            )

        with self._engine.conn.transaction():
            self._engine.conn.execute(
                "INSERT INTO incident_branches "
                "(id, org_id, incident_id, label, forked_at_hlc, remediations, is_actual) VALUES "
                + ", ".join(["(%s, %s, %s, %s, %s, %s, %s)"] * len(branch_rows)),
                [v for row in branch_rows for v in row],
            )
            self._engine.conn.execute(
                "INSERT INTO branch_outcomes (branch_id, recovered, recurred, time_to_recovery_s, "
                "unnecessary_actions, risk, cost, score, detail) VALUES "
                + ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(outcome_rows)),
                [v for row in outcome_rows for v in row],
            )

        self._engine.ledger.append_many(
            org_id,
            incident_id,
            [
                (
                    "branch_simulated",
                    {
                        "label": r.label,
                        "remediations": r.remediations,
                        "score": r.outcome.score,
                        "recovered": r.outcome.recovered,
                    },
                )
                for r in results
            ],
            actor="counterfactual",
        )
        return results

    def _scenario_for(self, incident_id: UUID | str, *, as_of_hlc: str | None = None) -> Scenario:
        incident = self._engine.incidents.get(incident_id, as_of_hlc=as_of_hlc)
        if incident is None:
            raise ValueError(f"unknown incident: {incident_id}")
        key = incident.get("scenario")
        if not key:
            raise ValueError(f"incident {incident_id} has no scenario; not eligible for replay")
        return get_scenario(str(key))

    def _promote_lesson(
        self, org_id: str, incident_id: UUID | str, scenario: Scenario, best: BranchResult
    ) -> str:
        steps = " then ".join(best.remediations)
        statement = (
            f"For '{scenario.true_cause}', the best simulation-backed remediation is '{steps}' "
            f"(permanent fix under the model; simulated score {best.outcome.score})."
        )
        procedure = self._engine.procedural.add(
            org_id,
            name=f"Verified remediation: {scenario.key}",
            trigger_pattern=scenario.description,
            steps=steps,
        )
        if procedure.id is not None:
            self._engine.procedural.record_outcome(procedure.id, success=True)
        self._engine.ledger.append(
            org_id,
            incident_id,
            "lesson_promoted",
            {"scenario": scenario.key, "best": best.remediations, "score": best.outcome.score},
            actor="counterfactual",
        )
        return statement

    def _persist_run(
        self,
        org_id: str,
        incident_id: UUID | str,
        scenario: Scenario,
        forked_at_hlc: str | None,
        comparison: Comparison,
        lesson: str | None,
    ) -> UUID:
        actual_id = comparison.actual.branch_id if comparison.actual else None
        summary = (
            f"best='{comparison.best.label}' (score {comparison.best.outcome.score}); "
            f"decision_regret={comparison.decision_regret}"
            + ("; lesson promoted" if lesson else "")
        )
        row = self._engine.conn.execute(
            "INSERT INTO simulation_runs (org_id, incident_id, forked_at_hlc, scenario, "
            "actual_branch_id, best_branch_id, decision_regret, summary) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
            (
                org_id,
                incident_id,
                forked_at_hlc,
                scenario.key,
                actual_id,
                comparison.best.branch_id,
                comparison.decision_regret,
                summary,
            ),
        ).fetchone()
        assert row is not None
        return UUID(str(row["id"]))
