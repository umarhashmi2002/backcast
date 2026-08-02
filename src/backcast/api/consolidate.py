"""Lambda: scheduled, evidence-preserving consolidation of resolved incidents.

Triggered by EventBridge. Idempotent: each incident is consolidated at most once
(tracked by ``incidents.consolidated_at``), then long-term memory is decayed.
"""

from __future__ import annotations

from typing import Any

from ..telemetry import get_logger
from .http import json_response, parse_body
from .runtime import get_engine

log = get_logger(__name__)


def handler(event: dict[str, Any], context: object = None) -> dict[str, Any]:
    body = parse_body(event) if isinstance(event, dict) else {}
    limit = int(body.get("limit", 25))
    org_filter = body.get("org_id")

    engine = get_engine()
    pending = engine.incidents.resolved_unconsolidated(org_id=org_filter, limit=limit)

    reports: list[dict[str, Any]] = []
    decayed_orgs: set[str] = set()
    for incident in pending:
        org = str(incident["org_id"])
        report = engine.consolidator.consolidate_incident(org, incident["id"])
        engine.incidents.mark_consolidated(incident["id"])
        if org not in decayed_orgs:
            engine.consolidator.decay(org)
            decayed_orgs.add(org)
        reports.append(
            {
                "incident_id": str(incident["id"]),
                "facts_created": report.facts_created,
                "facts_reinforced": report.facts_reinforced,
                "procedure_created": report.procedure_created,
            }
        )

    log.info("consolidate.batch", processed=len(reports))
    return json_response(200, {"consolidated": len(reports), "reports": reports})
