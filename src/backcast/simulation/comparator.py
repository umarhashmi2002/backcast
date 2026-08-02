"""Counterfactual comparator — ranks branches and computes decision regret."""

from __future__ import annotations

from dataclasses import dataclass

from .model import BranchOutcome


@dataclass
class BranchResult:
    branch_id: object  # UUID (kept loose to avoid import churn)
    label: str
    remediations: list[str]
    is_actual: bool
    outcome: BranchOutcome


@dataclass
class Comparison:
    ranked: list[BranchResult]  # best score first
    best: BranchResult
    actual: BranchResult | None
    decision_regret: float  # best.score - actual.score (0 if the actual choice was optimal)


def compare(branches: list[BranchResult]) -> Comparison:
    if not branches:
        raise ValueError("cannot compare an empty set of branches")
    ranked = sorted(branches, key=lambda b: b.outcome.score, reverse=True)
    best = ranked[0]
    actual = next((b for b in branches if b.is_actual), None)
    regret = round(best.outcome.score - actual.outcome.score, 4) if actual is not None else 0.0
    return Comparison(ranked=ranked, best=best, actual=actual, decision_regret=regret)
