"""Deterministic incident model — computes branch outcomes, never invents them."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import asdict, dataclass
from typing import Any

from .scenarios import Scenario


@dataclass
class BranchOutcome:
    recovered: bool  # permanently resolved the true cause
    recurred: bool  # only temporary relief was achieved; it would recur
    time_to_recovery_s: float
    unnecessary_actions: int
    applied_actions: int
    risk: float
    cost: float
    score: float  # higher is better; used to rank branches and compute regret

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def score_outcome(
    *,
    recovered: bool,
    recurred: bool,
    time_to_recovery_s: float,
    unnecessary_actions: int,
    risk: float,
    cost: float,
) -> float:
    """Blend correctness, speed, safety, and economy into a single comparable score."""
    base = 1.0 if recovered else 0.0
    penalties = (
        0.10 * unnecessary_actions
        + 0.20 * risk
        + 0.04 * cost
        + 0.20 * min(1.0, time_to_recovery_s / 600.0)
        + (0.30 if recurred else 0.0)
    )
    return round(base - penalties, 4)


class DeterministicIncidentModel:
    """Applies a remediation sequence to a scenario and computes the outcome."""

    def simulate(self, scenario: Scenario, remediations: Sequence[str]) -> BranchOutcome:
        resolved = False
        recurred = False
        time_s = 0.0
        risk = 0.0
        cost = 0.0
        unnecessary = 0

        for name in remediations:
            effect = scenario.remediations.get(name)
            if effect is None:
                unnecessary += 1  # an action not even applicable to this incident
                continue
            risk += effect.risk
            cost += effect.cost
            if resolved:
                unnecessary += 1  # acting after the incident is already fixed
                continue
            time_s += effect.recovery_seconds
            if effect.fixes:
                resolved = True
            elif effect.relieves:
                recurred = True  # bought time but did not fix the cause (insufficient, not wasted)
            else:
                unnecessary += 1  # no effect on this incident — a wasted action

        score = score_outcome(
            recovered=resolved,
            recurred=recurred,
            time_to_recovery_s=time_s,
            unnecessary_actions=unnecessary,
            risk=risk,
            cost=cost,
        )
        return BranchOutcome(
            recovered=resolved,
            recurred=recurred,
            time_to_recovery_s=time_s,
            unnecessary_actions=unnecessary,
            applied_actions=len(remediations),
            risk=round(risk, 4),
            cost=round(cost, 4),
            score=score,
        )
