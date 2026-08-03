"""Tiny HTTP helpers for Lambda handlers (API Gateway proxy + direct invoke)."""

from __future__ import annotations

import base64
import json
from typing import Any


def parse_body(event: dict[str, Any]) -> dict[str, Any]:
    """Return the request payload for both API Gateway proxy and direct invokes."""
    if "body" not in event:
        return event  # direct Lambda / EventBridge invoke: the event *is* the payload
    body = event.get("body")
    if isinstance(body, dict):
        return body
    if not body:
        return {}
    if event.get("isBase64Encoded"):
        body = base64.b64decode(body).decode("utf-8")
    parsed = json.loads(body)
    return parsed if isinstance(parsed, dict) else {}


def raw_body(event: dict[str, Any]) -> bytes:
    """Return the request body as raw bytes (for HMAC signature verification)."""
    body = event.get("body")
    if body is None:
        return b""
    if isinstance(body, bytes | bytearray):
        return bytes(body)
    if isinstance(body, dict):
        return json.dumps(body).encode("utf-8")
    if event.get("isBase64Encoded"):
        return base64.b64decode(body)
    return str(body).encode("utf-8")


def json_response(status: int, data: dict[str, Any]) -> dict[str, Any]:
    return {
        "statusCode": status,
        "headers": {"content-type": "application/json"},
        "body": json.dumps(data, default=str),
    }
