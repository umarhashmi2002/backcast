"""Append-only, hash-chained event ledger — permanent provenance.

Each incident has its own chain: ``entry_hash = sha256(prev_hash || seq ||
event_type || canonical(payload) || actor)``. Any tampering with a historical
entry breaks every subsequent hash, making the trail verifiable. Unlike
``AS OF SYSTEM TIME`` (bounded by the GC window) the ledger is durable forever.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from typing import Any
from uuid import UUID

import psycopg
from psycopg.types.json import Json
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_random_exponential

from ..db.connection import Connection
from .models import LedgerEntry

_RETRY_ERRORS = (psycopg.errors.SerializationFailure, psycopg.errors.UniqueViolation)


def _canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def compute_entry_hash(
    prev_hash: str | None, seq: int, event_type: str, payload: dict[str, Any], actor: str | None
) -> str:
    hasher = hashlib.sha256()
    hasher.update((prev_hash or "").encode("utf-8"))
    hasher.update(str(seq).encode("utf-8"))
    hasher.update(event_type.encode("utf-8"))
    hasher.update(_canonical(payload).encode("utf-8"))
    hasher.update((actor or "").encode("utf-8"))
    return hasher.hexdigest()


class EventLedger:
    """Writes and verifies the per-incident hash chain."""

    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    @retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_random_exponential(multiplier=0.05, max=1.0),
        retry=retry_if_exception_type(_RETRY_ERRORS),
    )
    def append(
        self,
        org_id: str,
        incident_id: UUID | str,
        event_type: str,
        payload: dict[str, Any],
        *,
        actor: str | None = None,
        model_id: str | None = None,
    ) -> LedgerEntry:
        """Atomically append an entry, extending the incident's hash chain."""
        with self._conn.transaction():
            prev = self._conn.execute(
                "SELECT seq, entry_hash FROM event_ledger "
                "WHERE incident_id = %s ORDER BY seq DESC LIMIT 1 FOR UPDATE",
                (incident_id,),
            ).fetchone()
            prev_seq = int(prev["seq"]) if prev else 0
            prev_hash = prev["entry_hash"] if prev else None
            seq = prev_seq + 1
            entry_hash = compute_entry_hash(prev_hash, seq, event_type, payload, actor)
            self._conn.execute(
                "INSERT INTO event_ledger "
                "(org_id, incident_id, seq, event_type, payload, actor, model_id, prev_hash, entry_hash) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    org_id,
                    incident_id,
                    seq,
                    event_type,
                    Json(payload),
                    actor,
                    model_id,
                    prev_hash,
                    entry_hash,
                ),
            )
        return LedgerEntry(
            incident_id=UUID(str(incident_id)),
            seq=seq,
            event_type=event_type,
            payload=payload,
            actor=actor,
            prev_hash=prev_hash,
            entry_hash=entry_hash,
        )

    @retry(
        reraise=True,
        stop=stop_after_attempt(6),
        wait=wait_random_exponential(multiplier=0.05, max=1.0),
        retry=retry_if_exception_type(_RETRY_ERRORS),
    )
    def append_many(
        self,
        org_id: str,
        incident_id: UUID | str,
        events: Sequence[tuple[str, dict[str, Any]]],
        *,
        actor: str | None = None,
        model_id: str | None = None,
    ) -> list[LedgerEntry]:
        """Append several entries as one transaction, extending the same chain.

        Identical semantics to calling :meth:`append` in a loop — the chain is
        still strictly sequential and ``verify`` recomputes it the same way — but
        it costs one round trip for the tip lookup and one multi-row INSERT
        instead of a transaction per entry. That matters on a Lambda talking to
        CockroachDB Cloud, where each round trip is ~200ms.
        """
        if not events:
            return []
        with self._conn.transaction():
            prev = self._conn.execute(
                "SELECT seq, entry_hash FROM event_ledger "
                "WHERE incident_id = %s ORDER BY seq DESC LIMIT 1 FOR UPDATE",
                (incident_id,),
            ).fetchone()
            seq = int(prev["seq"]) if prev else 0
            prev_hash: str | None = prev["entry_hash"] if prev else None

            entries: list[LedgerEntry] = []
            rows: list[tuple[Any, ...]] = []
            for event_type, payload in events:
                seq += 1
                entry_hash = compute_entry_hash(prev_hash, seq, event_type, payload, actor)
                rows.append(
                    (
                        org_id,
                        incident_id,
                        seq,
                        event_type,
                        Json(payload),
                        actor,
                        model_id,
                        prev_hash,
                        entry_hash,
                    )
                )
                entries.append(
                    LedgerEntry(
                        incident_id=UUID(str(incident_id)),
                        seq=seq,
                        event_type=event_type,
                        payload=payload,
                        actor=actor,
                        prev_hash=prev_hash,
                        entry_hash=entry_hash,
                    )
                )
                prev_hash = entry_hash

            placeholders = ", ".join(["(%s, %s, %s, %s, %s, %s, %s, %s, %s)"] * len(rows))
            self._conn.execute(
                "INSERT INTO event_ledger "
                "(org_id, incident_id, seq, event_type, payload, actor, model_id, prev_hash, entry_hash) "
                f"VALUES {placeholders}",
                [value for row in rows for value in row],
            )
        return entries

    def verify(self, incident_id: UUID | str) -> bool:
        """Recompute the chain and confirm no entry has been tampered with."""
        rows = self._conn.execute(
            "SELECT seq, event_type, payload, actor, prev_hash, entry_hash "
            "FROM event_ledger WHERE incident_id = %s ORDER BY seq",
            (incident_id,),
        ).fetchall()
        prev_hash: str | None = None
        for row in rows:
            expected = compute_entry_hash(
                prev_hash, int(row["seq"]), row["event_type"], row["payload"], row["actor"]
            )
            if expected != row["entry_hash"] or row["prev_hash"] != prev_hash:
                return False
            prev_hash = row["entry_hash"]
        return True
