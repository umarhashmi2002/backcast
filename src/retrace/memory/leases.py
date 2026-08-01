"""Transactional action leases — memory governs autonomous action.

The ``UNIQUE (org_id, action_key)`` constraint means that among any number of
concurrent workers proposing the same action, exactly one wins the claim. The
``idempotency_key`` and ``lease_expires_at`` support crash-safe execution: a
replacement worker can take over an expired lease and, because completion is
recorded transactionally, never double-executes a finished action.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Json

from ..db.connection import Connection
from .models import LeaseClaim, LeaseStatus


class ActionLeaseCoordinator:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def claim(
        self,
        org_id: str,
        incident_id: UUID | str | None,
        action_key: str,
        holder: str,
        *,
        ttl_seconds: int = 300,
        payload: dict[str, Any] | None = None,
        idempotency_key: str | None = None,
    ) -> LeaseClaim:
        """Attempt to claim ``action_key``. Returns won=True for the single winner."""
        idem = idempotency_key or str(uuid4())
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        row = self._conn.execute(
            "INSERT INTO action_leases "
            "(org_id, incident_id, action_key, idempotency_key, holder, lease_expires_at, payload) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s) "
            "ON CONFLICT (org_id, action_key) DO NOTHING "
            "RETURNING id, holder, status, idempotency_key",
            (org_id, incident_id, action_key, idem, holder, expires, Json(payload or {})),
        ).fetchone()
        if row is not None:
            return LeaseClaim(
                won=True,
                action_key=action_key,
                holder=row["holder"],
                status=LeaseStatus(row["status"]),
                lease_id=row["id"],
                idempotency_key=row["idempotency_key"],
            )
        existing = self._conn.execute(
            "SELECT holder, status FROM action_leases WHERE org_id = %s AND action_key = %s",
            (org_id, action_key),
        ).fetchone()
        return LeaseClaim(
            won=False,
            action_key=action_key,
            holder=holder,
            status=LeaseStatus(existing["status"]) if existing else LeaseStatus.claimed,
            existing_holder=existing["holder"] if existing else None,
        )

    def take_over_if_expired(
        self, org_id: str, action_key: str, holder: str, *, ttl_seconds: int = 300
    ) -> LeaseClaim | None:
        """Take over a lease whose holder has crashed (lease expired). None if not takeable."""
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        row = self._conn.execute(
            "UPDATE action_leases SET holder = %s, lease_expires_at = %s, "
            "attempts = attempts + 1, status = 'claimed', updated_at = now() "
            "WHERE org_id = %s AND action_key = %s "
            "AND status IN ('claimed', 'executing') AND lease_expires_at < now() "
            "RETURNING id, holder, status, idempotency_key",
            (holder, expires, org_id, action_key),
        ).fetchone()
        if row is None:
            return None
        return LeaseClaim(
            won=True,
            action_key=action_key,
            holder=row["holder"],
            status=LeaseStatus(row["status"]),
            lease_id=row["id"],
            idempotency_key=row["idempotency_key"],
        )

    def mark_executing(self, lease_id: UUID | str) -> None:
        self._conn.execute(
            "UPDATE action_leases SET status = 'executing', updated_at = now() WHERE id = %s",
            (lease_id,),
        )

    def complete(self, lease_id: UUID | str, result: dict[str, Any] | None = None) -> None:
        self._conn.execute(
            "UPDATE action_leases SET status = 'completed', result = %s, updated_at = now() "
            "WHERE id = %s",
            (Json(result or {}), lease_id),
        )

    def fail(self, lease_id: UUID | str, error: str) -> None:
        self._conn.execute(
            "UPDATE action_leases SET status = 'failed', error = %s, updated_at = now() WHERE id = %s",
            (error, lease_id),
        )

    def get(self, org_id: str, action_key: str) -> dict[str, Any] | None:
        return self._conn.execute(
            "SELECT id, holder, status, idempotency_key, attempts, result, error, lease_expires_at "
            "FROM action_leases WHERE org_id = %s AND action_key = %s",
            (org_id, action_key),
        ).fetchone()
