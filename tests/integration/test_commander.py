"""End-to-end test of the Incident Commander loop with a scripted LLM.

Exercises the full agent loop (recall → observe → assess → remediate → resolve)
against a live CockroachDB, with no AWS dependency.
"""

from __future__ import annotations

import pytest

from retrace.agent import IncidentCommander, LLMResponse, ScriptedLLM, ToolUse
from retrace.memory import MemoryEngine

pytestmark = pytest.mark.integration


def test_commander_investigates_and_remediates(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "payments-api 5xx", "payments-api")["id"]

    scripted = ScriptedLLM(
        [
            LLMResponse(
                text="Checking history and recording what I see.",
                tool_uses=[
                    ToolUse(
                        "u1", "recall_similar_incidents", {"query": "payments 5xx connection pool"}
                    ),
                    ToolUse(
                        "u2",
                        "record_observation",
                        {"kind": "metric", "content": "error rate 5%, pool 94%"},
                    ),
                ],
                stop_reason="tool_use",
            ),
            LLMResponse(
                text="Deploy correlation is strong; proposing rollback.",
                tool_uses=[
                    ToolUse(
                        "u3",
                        "assess_hypothesis",
                        {
                            "hypothesis": "deploy v2.4.1 connection leak",
                            "confidence": 0.86,
                            "rationale": "correlated",
                        },
                    ),
                    ToolUse(
                        "u4",
                        "propose_remediation",
                        {"action": "rollback-v2.4.1", "rationale": "high confidence"},
                    ),
                ],
                stop_reason="tool_use",
            ),
            LLMResponse(
                text="Root cause: deploy v2.4.1 connection leak. Rolling back.",
                tool_uses=[],
                stop_reason="end_turn",
            ),
        ]
    )

    commander = IncidentCommander(engine, scripted)
    result = commander.handle(
        org, iid, "payments-api returning 5xx; pool saturated", worker_id="worker-1"
    )

    assert result.steps == 3
    assert "record_observation" in result.tool_calls
    assert result.claimed_action is not None

    beliefs = engine.beliefs.current_beliefs(iid)
    assert any(b.confidence == pytest.approx(0.86) for b in beliefs)

    lease = engine.leases.get(org, result.claimed_action)
    assert lease is not None
    assert lease["holder"] == "worker-1"

    assert engine.ledger.verify(iid) is True


def test_commander_stands_down_on_lost_lease(engine: MemoryEngine, org: str) -> None:
    iid = engine.incidents.create(org, "payments-api 5xx", "payments-api")["id"]
    action_key = f"rollback-v2.4.1:{iid}"
    # Another worker already holds the action lease.
    engine.leases.claim(org, iid, action_key, holder="worker-first")

    scripted = ScriptedLLM(
        [
            LLMResponse(
                text="Proposing rollback.",
                tool_uses=[
                    ToolUse(
                        "u1", "propose_remediation", {"action": "rollback-v2.4.1", "rationale": "x"}
                    )
                ],
                stop_reason="tool_use",
            ),
            LLMResponse(
                text="Another worker owns the rollback; standing down.",
                tool_uses=[],
                stop_reason="end_turn",
            ),
        ]
    )
    result = IncidentCommander(engine, scripted).handle(org, iid, "5xx", worker_id="worker-2")

    assert result.claimed_action is None  # did not win the lease
    lease = engine.leases.get(org, action_key)
    assert lease is not None
    assert lease["holder"] == "worker-first"
