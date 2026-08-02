"""Unit tests for distillation (no DB/AWS)."""

from __future__ import annotations

from backcast.memory.consolidation import LLMDistiller, RuleBasedDistiller, _extract_json


def test_rule_based_distiller_with_resolution() -> None:
    result = RuleBasedDistiller().distill(
        service="payments-api",
        top_hypothesis="deploy v2.4.1 connection leak",
        evidence_texts=["5xx spike"],
        resolution="rolled back v2.4.1",
    )
    assert len(result.facts) == 2
    assert result.procedure is not None
    assert result.procedure.steps == "rolled back v2.4.1"


def test_rule_based_distiller_without_resolution() -> None:
    result = RuleBasedDistiller().distill(
        service="svc", top_hypothesis="something", evidence_texts=[], resolution=None
    )
    assert result.procedure is None


def test_llm_distiller_parses_messy_json() -> None:
    def fake_complete(system: str, prompt: str) -> str:
        return (
            'Sure! ```json\n{"facts":[{"statement":"pool leaks under load","confidence":0.8}],'
            '"procedure":{"name":"bump pool","trigger_pattern":"pool exhausted","steps":"raise max"}}\n```'
        )

    result = LLMDistiller(fake_complete).distill(
        service="svc", top_hypothesis="h", evidence_texts=["e"], resolution="r"
    )
    assert result.facts[0].statement == "pool leaks under load"
    assert result.facts[0].confidence == 0.8
    assert result.procedure is not None
    assert result.procedure.steps == "raise max"


def test_extract_json_tolerates_garbage() -> None:
    assert _extract_json("no json at all") == {}
