"""The Incident Commander orchestration loop.

Drives an LLM tool-use loop over the memory engine: the model recalls similar
incidents, records evidence, forms and revises beliefs, and proposes remediation
through the transactional action lease — every step recorded in the ledger.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import UUID

from ..memory import MemoryEngine
from ..telemetry import get_logger
from .llm import LLM, Message, ToolResult
from .prompts import SYSTEM_PROMPT
from .tools import TOOL_SPECS, AgentTools

log = get_logger(__name__)


@dataclass
class CommanderResult:
    incident_id: UUID
    final_text: str
    steps: int
    tool_calls: list[str] = field(default_factory=list)
    claimed_action: str | None = None
    # Working-memory session holding this turn's scratchpad (TTL-expired).
    session_id: UUID | None = None


class IncidentCommander:
    """Runs one incident to a conclusion using an LLM + the memory tools."""

    def __init__(self, engine: MemoryEngine, llm: LLM, *, max_steps: int = 12) -> None:
        self._engine = engine
        self._llm = llm
        self._max_steps = max_steps

    def handle(
        self, org_id: str, incident_id: UUID | str, signal: str, *, worker_id: str = "agent"
    ) -> CommanderResult:
        tools = AgentTools(self._engine, org_id, incident_id, worker_id=worker_id)
        iid = UUID(str(incident_id))
        messages: list[Message] = [
            Message(
                role="user",
                text=(
                    f"A new incident signal has arrived for org '{org_id}'.\n\n"
                    f"Signal:\n{signal}\n\n"
                    "Diagnose it and take appropriate action. Use your tools."
                ),
            )
        ]
        tool_calls: list[str] = []
        claimed_action: str | None = None

        # The turn log is working memory: a disposable scratchpad that CockroachDB
        # expires on its own (Row-Level TTL). Persisting it means a worker that
        # takes over a fenced lease, or a reviewer afterwards, can see the context
        # a decision was made in. Nothing here is a source of truth.
        working = self._engine.working
        session_id = working.open_session(org_id, iid, worker_id=worker_id)
        working.record_turns(org_id, session_id, [("user", signal)], incident_id=iid)

        for step in range(self._max_steps):
            response = self._llm.converse(SYSTEM_PROMPT, messages, TOOL_SPECS)
            messages.append(
                Message(role="assistant", text=response.text, tool_uses=response.tool_uses)
            )

            if response.stop_reason != "tool_use" or not response.tool_uses:
                log.info("commander.done", incident_id=str(iid), steps=step + 1)
                working.record_turns(
                    org_id, session_id, [("assistant", response.text)], incident_id=iid
                )
                working.close_session(session_id, summary=response.text[:2000] or None)
                return CommanderResult(
                    incident_id=iid,
                    final_text=response.text,
                    steps=step + 1,
                    tool_calls=tool_calls,
                    claimed_action=claimed_action,
                    session_id=session_id,
                )

            results: list[ToolResult] = []
            for use in response.tool_uses:
                tool_calls.append(use.name)
                output, is_error = tools.dispatch(use.name, use.input)
                if use.name == "propose_remediation" and output.get("claimed"):
                    claimed_action = str(output.get("action_key"))
                results.append(ToolResult(use.tool_use_id, output, is_error=is_error))
            messages.append(Message(role="user", tool_results=results))

            # One batched write per step rather than per turn: a Lambda pays a
            # round trip per statement against CockroachDB Cloud.
            turns: list[tuple[str, str]] = []
            if response.text:
                turns.append(("assistant", response.text))
            turns.append(
                (
                    "tool",
                    ", ".join(
                        f"{u.name} -> {r.content}"
                        for u, r in zip(response.tool_uses, results, strict=True)
                    ),
                )
            )
            working.record_turns(org_id, session_id, turns, incident_id=iid)

        log.warning("commander.max_steps", incident_id=str(iid), steps=self._max_steps)
        working.close_session(session_id, summary="reached step limit before concluding")
        return CommanderResult(
            incident_id=iid,
            final_text="Reached step limit before concluding.",
            steps=self._max_steps,
            tool_calls=tool_calls,
            claimed_action=claimed_action,
            session_id=session_id,
        )
