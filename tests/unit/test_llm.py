"""Unit tests for the LLM adapter (no AWS/DB)."""

from __future__ import annotations

from retrace.agent.llm import (
    LLMResponse,
    Message,
    ScriptedLLM,
    ToolResult,
    ToolUse,
    _encode_message,
)


def test_encode_text_message() -> None:
    assert _encode_message(Message(role="user", text="hello")) == {
        "role": "user",
        "content": [{"text": "hello"}],
    }


def test_encode_tool_use_and_result() -> None:
    assistant = Message(
        role="assistant", text="thinking", tool_uses=[ToolUse("t1", "recall", {"query": "x"})]
    )
    enc = _encode_message(assistant)
    assert enc["content"][0] == {"text": "thinking"}
    assert enc["content"][1]["toolUse"] == {
        "toolUseId": "t1",
        "name": "recall",
        "input": {"query": "x"},
    }

    user = Message(role="user", tool_results=[ToolResult("t1", {"ok": True})])
    result_block = _encode_message(user)["content"][0]["toolResult"]
    assert result_block["toolUseId"] == "t1"
    assert result_block["content"] == [{"json": {"ok": True}}]
    assert "status" not in result_block


def test_scripted_llm_replays_then_defaults() -> None:
    first = LLMResponse("done", [], "end_turn")
    llm = ScriptedLLM([first])
    assert llm.converse("sys", [Message(role="user", text="hi")], []) is first
    fallback = llm.converse("sys", [], [])
    assert fallback.stop_reason == "end_turn"
    assert len(llm.calls) == 2
