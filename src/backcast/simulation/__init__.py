"""Counterfactual incident replay: rewind → fork → simulate → compare → learn.

Outcomes are computed by a deterministic incident model, never invented by an LLM.
"""

from __future__ import annotations

from .branches import CounterfactualService, SimulationReport
from .comparator import BranchResult, Comparison, compare
from .model import BranchOutcome, DeterministicIncidentModel, score_outcome
from .scenarios import SCENARIOS, RemediationEffect, Scenario, get_scenario

__all__ = [
    "SCENARIOS",
    "BranchOutcome",
    "BranchResult",
    "Comparison",
    "CounterfactualService",
    "DeterministicIncidentModel",
    "RemediationEffect",
    "Scenario",
    "SimulationReport",
    "compare",
    "get_scenario",
    "score_outcome",
]
