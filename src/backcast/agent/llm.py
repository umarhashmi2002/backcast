"""Provider-agnostic LLM interface for the agent loop.

``BedrockLLM`` speaks the Amazon Bedrock Converse API (Claude), including tool
use. ``ScriptedLLM`` replays a fixed sequence of responses so the whole agent
loop can be tested offline without AWS. The rest of the agent depends only on
the :class:`LLM` protocol.
"""

from __future__ import annotations

from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from ..config import get_settings
from ..telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    input_schema: dict[str, Any]  # JSON Schema for the tool's input object


@dataclass
class ToolUse:
    tool_use_id: str
    name: str
    input: dict[str, Any]


@dataclass
class ToolResult:
    tool_use_id: str
    content: dict[str, Any]
    is_error: bool = False


@dataclass
class Message:
    role: str  # "user" | "assistant"
    text: str | None = None
    tool_uses: list[ToolUse] = field(default_factory=list)
    tool_results: list[ToolResult] = field(default_factory=list)


@dataclass
class LLMResponse:
    text: str
    tool_uses: list[ToolUse]
    stop_reason: str  # "end_turn" | "tool_use" | "max_tokens" | ...


class LLM(Protocol):
    def converse(
        self, system: str, messages: list[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse: ...


class BedrockLLM:
    """Claude on Amazon Bedrock via the Converse API."""

    def __init__(
        self,
        model_id: str | None = None,
        region: str | None = None,
        *,
        max_tokens: int = 2048,
        temperature: float = 0.2,
    ) -> None:
        import boto3

        settings = get_settings()
        self.model_id = model_id or settings.bedrock_model_id
        self.max_tokens = max_tokens
        self.temperature = temperature
        # Typed as Any: the Converse request/response TypedDicts are deeply
        # nested and add no safety to this thin adapter.
        self._client: Any = boto3.client(
            "bedrock-runtime", region_name=region or settings.aws_region
        )

    def converse(
        self, system: str, messages: list[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        request: dict[str, Any] = {
            "modelId": self.model_id,
            "system": [{"text": system}],
            "messages": [_encode_message(m) for m in messages],
            "inferenceConfig": {"maxTokens": self.max_tokens, "temperature": self.temperature},
        }
        if tools:
            request["toolConfig"] = {
                "tools": [
                    {
                        "toolSpec": {
                            "name": t.name,
                            "description": t.description,
                            "inputSchema": {"json": t.input_schema},
                        }
                    }
                    for t in tools
                ]
            }
        response: Any = self._client.converse(**request)
        message = response["output"]["message"]
        text_parts: list[str] = []
        tool_uses: list[ToolUse] = []
        for block in message["content"]:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                use = block["toolUse"]
                tool_uses.append(
                    ToolUse(use["toolUseId"], use["name"], dict(use.get("input") or {}))
                )
        return LLMResponse(
            text="\n".join(text_parts).strip(),
            tool_uses=tool_uses,
            stop_reason=str(response["stopReason"]),
        )


def _encode_message(message: Message) -> dict[str, Any]:
    content: list[dict[str, Any]] = []
    if message.text:
        content.append({"text": message.text})
    for use in message.tool_uses:
        content.append(
            {"toolUse": {"toolUseId": use.tool_use_id, "name": use.name, "input": use.input}}
        )
    for result in message.tool_results:
        block: dict[str, Any] = {
            "toolResult": {
                "toolUseId": result.tool_use_id,
                "content": [{"json": result.content}],
            }
        }
        if result.is_error:
            block["toolResult"]["status"] = "error"
        content.append(block)
    return {"role": message.role, "content": content}


class ScriptedLLM:
    """Replays a fixed queue of responses; for offline tests and demos."""

    def __init__(self, responses: Sequence[LLMResponse]) -> None:
        self._responses: deque[LLMResponse] = deque(responses)
        self.calls: list[list[Message]] = []

    def converse(
        self, system: str, messages: list[Message], tools: Sequence[ToolSpec]
    ) -> LLMResponse:
        self.calls.append(list(messages))
        if self._responses:
            return self._responses.popleft()
        return LLMResponse(
            text="(no more scripted responses)", tool_uses=[], stop_reason="end_turn"
        )
