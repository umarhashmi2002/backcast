"""Transactional action leases with fencing — memory governs autonomous action.

``UNIQUE (org_id, action_key)`` guarantees a single current owner even under a
thundering herd. But safe autonomy needs more than that, because the database
cannot atomically commit a transaction together with an external side effect:

* **Fencing.** Every takeover bumps ``lease_generation``. All writes/completions
  are gated on ``holder = me AND lease_generation = mine AND not expired``, so a
  stale (crashed/paused) previous holder that "revives" is rejected — it cannot
  finalize after generation N+1 has been issued.
* **Idempotency.** ``UNIQUE (idempotency_key)`` + caller-side idempotency tokens
  make the external action safely repeatable.
* **Liveness.** ``heartbeat`` keeps a long-running holder's lease alive; failing
  to heartbeat lets a replacement take over safely.

This gives "exactly one current logical owner and one canonical action intent,
with safely repeatable execution" — not a false "exactly-once external effect".
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from psycopg.types.json import Json

from ..db.connection import Connection
from .models import LeaseClaim, LeaseStatus

_RETURNING = "id, holder, status, idempotency_key, lease_generation"


class ActionLeaseCoordinator:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def _claim_from_row(self, row: dict[str, Any], action_key: str, *, won: bool) -> LeaseClaim:
        return LeaseClaim(
            won=won,
            action_key=action_key,
            holder=row["holder"],
            status=LeaseStatus(row["status"]),
            lease_id=row["id"],
            idempotency_key=row["idempotency_key"],
            lease_generation=int(row["lease_generation"]),
        )

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
            f"RETURNING {_RETURNING}",
            (org_id, incident_id, action_key, idem, holder, expires, Json(payload or {})),
        ).fetchone()
        if row is not None:
            return self._claim_from_row(row, action_key, won=True)
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
        """Take over an expired lease, bumping the fencing generation. None if not takeable."""
        expires = datetime.now(UTC) + timedelta(seconds=ttl_seconds)
        row = self._conn.execute(
            "UPDATE action_leases SET holder = %s, lease_expires_at = %s, "
            "lease_generation = lease_generation + 1, heartbeat_at = now(), "
            "attempts = attempts + 1, status = 'claimed', updated_at = now() "
            "WHERE org_id = %s AND action_key = %s "
            "AND status IN ('claimed', 'executing') AND lease_expires_at < now() "
            f"RETURNING {_RETURNING}",
            (holder, expires, org_id, action_key),
        ).fetchone()
        return None if row is None else self._claim_from_row(row, action_key, won=True)

    # --- fenced mutations: succeed only for the current, unexpired holder ---
    def _fenced_update(
        self,
        set_clause: str,
        params: tuple[Any, ...],
        *,
        lease_id: UUID | str,
        holder: str,
        generation: int,
    ) -> bool:
        row = self._conn.execute(
            f"UPDATE action_leases SET {set_clause}, updated_at = now() "
            "WHERE id = %s AND holder = %s AND lease_generation = %s AND lease_expires_at > now() "
            "RETURNING id",
            (*params, lease_id, holder, generation),
        ).fetchone()
        return row is not None

    def heartbeat(self, lease_id: UUID | str, holder: str, generation: int) -> bool:
        """Prove liveness. Returns False if the lease was taken over or expired (fenced)."""
        return self._fenced_update(
            "heartbeat_at = now()", (), lease_id=lease_id, holder=holder, generation=generation
        )

    def mark_executing(self, lease_id: UUID | str, holder: str, generation: int) -> bool:
        return self._fenced_update(
            "status = 'executing', heartbeat_at = now()",
            (),
            lease_id=lease_id,
            holder=holder,
            generation=generation,
        )

    def complete(
        self,
        lease_id: UUID | str,
        holder: str,
        generation: int,
        result: dict[str, Any] | None = None,
    ) -> bool:
        """Mark completed. Returns False if fenced (a newer generation took over)."""
        return self._fenced_update(
            "status = 'completed', result = %s",
            (Json(result or {}),),
            lease_id=lease_id,
            holder=holder,
            generation=generation,
        )

    def fail(self, lease_id: UUID | str, holder: str, generation: int, error: str) -> bool:
        return self._fenced_update(
            "status = 'failed', error = %s",
            (error,),
            lease_id=lease_id,
            holder=holder,
            generation=generation,
        )

    def get(self, org_id: str, action_key: str) -> dict[str, Any] | None:
        return self._conn.execute(
            "SELECT id, holder, status, idempotency_key, lease_generation, attempts, "
            "result, error, lease_expires_at, heartbeat_at "
            "FROM action_leases WHERE org_id = %s AND action_key = %s",
            (org_id, action_key),
        ).fetchone()
