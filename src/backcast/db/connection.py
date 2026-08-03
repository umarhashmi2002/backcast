"""CockroachDB connection management (psycopg 3).

Design notes
------------
* We keep dependencies minimal and do not use a connection pool: on AWS Lambda
  a pool provides little benefit and complicates lifecycle. Instead we cache a
  single connection per warm execution environment (:func:`shared_connection`).
* Vectors are sent as text literals cast to ``VECTOR`` (``%s::VECTOR``) so we
  need no extra pgvector adapter and stay portable across driver versions.
* Transient connection failures are retried with exponential backoff.
"""

from __future__ import annotations

import contextlib
from collections.abc import Iterator, Sequence
from typing import Any

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.rows import dict_row
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from ..config import get_settings
from ..telemetry import get_logger

log = get_logger(__name__)

# Public type aliases for annotations elsewhere in the codebase.
Connection = psycopg.Connection[dict[str, Any]]
Cursor = psycopg.Cursor[dict[str, Any]]

_shared: Connection | None = None


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=0.2, max=5),
    retry=retry_if_exception_type(psycopg.OperationalError),
)
def connect(dsn: str | None = None) -> Connection:
    """Open a new CockroachDB connection with dict rows. Retries on failure."""
    settings = get_settings()
    conn: Connection = psycopg.connect(
        dsn or settings.database_url,
        row_factory=dict_row,
        autocommit=False,
        application_name="backcast",
    )
    return conn


def shared_connection() -> Connection:
    """Return a process-cached connection, reconnecting if it has gone stale.

    Intended for Lambda warm-start reuse. Verifies liveness with ``SELECT 1``
    and resets any lingering/aborted transaction state before returning.
    """
    global _shared
    if _shared is not None and not _shared.closed:
        try:
            _shared.rollback()
            with _shared.cursor() as cur:
                cur.execute("SELECT 1")
            return _shared
        except psycopg.Error:
            log.warning("shared_connection.stale_reconnect")
            with contextlib.suppress(Exception):
                _shared.close()
            _shared = None
    _shared = connect()
    return _shared


@contextlib.contextmanager
def transaction(conn: Connection | None = None) -> Iterator[Cursor]:
    """Yield a cursor inside a transaction; commit on success, rollback on error.

    Pass an existing ``conn`` to participate in the caller's transaction scope;
    otherwise a dedicated connection is opened and closed.
    """
    own = conn is None
    active = conn if conn is not None else connect()
    try:
        with active.cursor() as cur:
            yield cur
        active.commit()
    except Exception:
        with contextlib.suppress(Exception):
            active.rollback()
        raise
    finally:
        if own:
            active.close()


def vector_literal(values: Sequence[float]) -> str:
    """Format an embedding as a CockroachDB ``VECTOR`` text literal.

    Use with an explicit cast, e.g. ``cur.execute(sql, [vector_literal(v)])``
    where ``sql`` contains ``%s::VECTOR``.
    """
    return "[" + ",".join(f"{float(x):.7g}" for x in values) + "]"


def parse_vector(text: str | None) -> list[float]:
    """Parse a CockroachDB ``VECTOR`` rendered as text (``[1,2,3]``) back to floats."""
    if not text:
        return []
    inner = text.strip().removeprefix("[").removesuffix("]")
    return [float(x) for x in inner.split(",") if x.strip()]


def admin_dsn(dsn: str, admin_db: str = "defaultdb") -> str:
    """Return ``dsn`` rewritten to connect to a maintenance database."""
    params = conninfo_to_dict(dsn)
    params["dbname"] = admin_db
    return make_conninfo("", **params)


def target_database(dsn: str) -> str:
    """Extract the target database name from a DSN (defaults to ``backcast``)."""
    return str(conninfo_to_dict(dsn).get("dbname") or "backcast")
