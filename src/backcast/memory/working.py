"""Working memory — the agent's live scratchpad, physically expired by Row-Level TTL.

This is the one genuinely disposable tier. Every other tier is either immutable
(evidence, ledger) or versioned (beliefs, semantic, procedural); a session's turns
are context, not record, so ``working_memory`` carries
``ttl_expire_after = '24 hours'`` and CockroachDB deletes the rows itself. Nothing
here is a source of truth — anything worth keeping is promoted into evidence,
beliefs, or the ledger before the TTL reclaims it.

Persisting turns (rather than holding them only in a Python list) means a crashed
or taken-over worker can see what the previous holder was reasoning about, and a
reviewer can reconstruct the context a decision was made in for as long as the
window lasts.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any
from uuid import UUID

from ..db.connection import Connection


class WorkingMemoryStore:
    """Session-scoped conversational turns with a database-enforced lifetime."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def open_session(
        self,
        org_id: str,
        incident_id: UUID | str | None = None,
        *,
        worker_id: str | None = None,
    ) -> UUID:
        row = self._conn.execute(
            "INSERT INTO agent_sessions (org_id, incident_id, worker_id) "
            "VALUES (%s, %s, %s) RETURNING id",
            (org_id, incident_id, worker_id),
        ).fetchone()
        assert row is not None
        return UUID(str(row["id"]))

    def record_turns(
        self,
        org_id: str,
        session_id: UUID | str,
        turns: Sequence[tuple[str, str]],
        *,
        incident_id: UUID | str | None = None,
    ) -> int:
        """Append ``(role, content)`` turns in one round trip. Returns rows written.

        Batched because the agent loop adds one or two turns per step, and a
        Lambda pays a full round trip per statement against CockroachDB Cloud.
        """
        if not turns:
            return 0
        # turn_seq comes from a scalar subquery over this session's existing rows.
        # The subquery reads the statement's snapshot, so every row sees the same
        # maximum and the literal offset makes each one distinct — giving a stable
        # order without spending a second round trip on a SELECT max().
        values: list[str] = []
        params: list[Any] = []
        for offset, (role, content) in enumerate(turns, start=1):
            values.append(
                "(%s, %s, %s, %s, %s, %s, "
                "(SELECT coalesce(max(turn_seq), 0) FROM working_memory WHERE session_id = %s) + %s)"
            )
            params.extend(
                (
                    org_id,
                    session_id,
                    incident_id,
                    role,
                    content,
                    # A cheap token estimate (~4 chars/token) is enough to drive
                    # context trimming; it is never used for billing.
                    max(1, len(content) // 4),
                    session_id,
                    offset,
                )
            )
        self._conn.execute(
            "INSERT INTO working_memory "
            "(org_id, session_id, incident_id, role, content, token_estimate, turn_seq) VALUES "
            + ", ".join(values),
            params,
        )
        self._conn.execute(
            "UPDATE agent_sessions SET last_active_at = now() WHERE id = %s", (session_id,)
        )
        return len(values)

    def turns(self, session_id: UUID | str, *, limit: int = 200) -> list[dict[str, Any]]:
        """Return the session's surviving turns, oldest first."""
        return self._conn.execute(
            "SELECT role, content, token_estimate, turn_seq, created_at FROM working_memory "
            "WHERE session_id = %s ORDER BY turn_seq LIMIT %s",
            (session_id, limit),
        ).fetchall()

    def close_session(self, session_id: UUID | str, summary: str | None = None) -> None:
        self._conn.execute(
            "UPDATE agent_sessions SET summary = %s, last_active_at = now() WHERE id = %s",
            (summary, session_id),
        )

    def ttl_expire_after(self) -> str | None:
        """Return the configured Row-Level TTL for ``working_memory``, if any.

        Read from the live schema so the demo asserts what the cluster is actually
        enforcing rather than what the migration once said.
        """
        row = self._conn.execute(
            "SELECT create_statement FROM [SHOW CREATE TABLE working_memory]"
        ).fetchone()
        if row is None:
            return None
        statement = str(row["create_statement"])
        marker = "ttl_expire_after = '"
        start = statement.find(marker)
        if start == -1:
            return None
        start += len(marker)
        end = statement.find("'", start)
        return statement[start:end] if end != -1 else None
