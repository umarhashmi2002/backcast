"""Lambda: run one Incident Commander turn (Bedrock Claude + memory tools)."""

from __future__ import annotations

from typing import Any

from ..agent import BedrockLLM, IncidentCommander
from ..telemetry import get_logger
from .http import json_response, parse_body
from .runtime import get_engine

log = get_logger(__name__)


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    body = parse_body(event)
    missing = [k for k in ("org_id", "incident_id", "signal") if k not in body]
    if missing:
        return json_response(400, {"error": f"missing fields: {', '.join(missing)}"})

    org = str(body["org_id"])
    incident_id = str(body["incident_id"])
    signal = str(body["signal"])
    worker_id = str(body.get("worker_id", "lambda-agent"))

    engine = get_engine()
    commander = IncidentCommander(engine, BedrockLLM())
    result = commander.handle(org, incident_id, signal, worker_id=worker_id)
    log.info("commander.done", incident_id=incident_id, steps=result.steps)

    return json_response(
        200,
        {
            "incident_id": str(result.incident_id),
            "summary": result.final_text,
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "claimed_action": result.claimed_action,
        },
    )
