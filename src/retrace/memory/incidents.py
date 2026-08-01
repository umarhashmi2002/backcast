"""Incident state-machine store (the operational, strongly-consistent record)."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from psycopg.types.json import Json

from ..db.connection import Connection
from .models import IncidentStatus, Severity


class IncidentStore:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def create(
        self,
        org_id: str,
        title: str,
        service: str,
        *,
        severity: Severity = Severity.sev3,
        external_id: str | None = None,
        summary: str | None = None,
        labels: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        row = self._conn.execute(
            "INSERT INTO incidents (org_id, external_id, title, summary, service, severity, labels) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "RETURNING id, state_version, status, created_at",
            (org_id, external_id, title, summary, service, severity.value, Json(labels or {})),
        ).fetchone()
        assert row is not None
        return row

    def get(self, incident_id: UUID | str) -> dict[str, Any] | None:
        return self._conn.execute(
            "SELECT id, org_id, external_id, title, summary, service, severity, status, "
            "state_version, resolution, created_at, resolved_at "
            "FROM incidents WHERE id = %s",
            (incident_id,),
        ).fetchone()

    def set_status(
        self,
        incident_id: UUID | str,
        status: IncidentStatus,
        *,
        resolution: str | None = None,
    ) -> dict[str, Any]:
        """Transition status and bump ``state_version``; stamps lifecycle times."""
        row = self._conn.execute(
            "UPDATE incidents SET status = %s, state_version = state_version + 1, updated_at = now(), "
            "acknowledged_at = CASE WHEN %s = 'acknowledged' AND acknowledged_at IS NULL "
            "THEN now() ELSE acknowledged_at END, "
            "resolved_at = CASE WHEN %s = 'resolved' THEN now() ELSE resolved_at END, "
            "closed_at = CASE WHEN %s = 'closed' THEN now() ELSE closed_at END, "
            "resolution = COALESCE(%s, resolution) "
            "WHERE id = %s RETURNING id, status, state_version",
            (status.value, status.value, status.value, status.value, resolution, incident_id),
        ).fetchone()
        assert row is not None
        return row
