"""Lambda: ingest an alert webhook into an incident (idempotent on fingerprint)."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

from ..memory.models import Severity
from ..telemetry import get_logger
from .http import json_response, parse_body
from .runtime import get_engine, put_artifact

log = get_logger(__name__)


def _severity(value: object) -> Severity:
    try:
        return Severity(str(value)) if value else Severity.sev3
    except ValueError:
        return Severity.sev3


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    body = parse_body(event)
    org = str(body.get("org_id", "default"))
    external_id = str(body.get("fingerprint") or body.get("external_id") or uuid4().hex)
    engine = get_engine()

    row, created = engine.incidents.upsert(
        org,
        external_id,
        title=str(body.get("title", "Alert")),
        service=str(body.get("service", "unknown")),
        severity=_severity(body.get("severity")),
        summary=body.get("summary"),
        labels=body.get("labels"),
    )
    incident_id = row["id"]
    if created:
        engine.ledger.append(
            org,
            incident_id,
            "incident_opened",
            {"external_id": external_id, "service": str(body.get("service", "unknown"))},
            actor="ingest",
        )
    artifact = put_artifact(org, str(incident_id), body)
    log.info("ingest.done", incident_id=str(incident_id), created=created)

    return json_response(
        201 if created else 200,
        {
            "incident_id": str(incident_id),
            "created": created,
            "status": row["status"],
            "artifact": artifact,
        },
    )
