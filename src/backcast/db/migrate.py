"""Minimal, idempotent SQL migration runner for CockroachDB.

Applies ``db/migrations/*.sql`` in lexical order, tracking applied versions in a
``schema_migrations`` table. DDL statements run in autocommit mode (CockroachDB
schema changes commit individually), and "object already exists" errors are
tolerated so a partially-applied migration can be safely re-run.

Usage::

    python -m backcast.db.migrate
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg

from ..config import get_settings
from ..telemetry import configure_logging, get_logger
from .connection import Connection, admin_dsn, connect, target_database

log = get_logger(__name__)

# SQLSTATEs meaning "this object already exists" — safe to skip on re-run.
_DUPLICATE_SQLSTATES = {
    "42P07",  # duplicate_table / relation (also indexes)
    "42710",  # duplicate_object (e.g. type)
    "42701",  # duplicate_column
    "42P06",  # duplicate_schema
    "42723",  # duplicate_function
}
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def find_migrations_dir() -> Path:
    """Locate the ``db/migrations`` directory (env override, else search up)."""
    if env := os.getenv("BACKCAST_MIGRATIONS_DIR"):
        return Path(env)
    cwd = Path.cwd()
    for base in (cwd, *cwd.parents):
        candidate = base / "db" / "migrations"
        if candidate.is_dir():
            return candidate
    return Path(__file__).resolve().parents[3] / "db" / "migrations"


def split_statements(sql: str) -> list[str]:
    """Split a SQL script into statements on top-level semicolons.

    Quote- and comment-aware: semicolons inside ``'...'`` / ``"..."`` literals
    (including ``''`` escapes), ``-- line`` comments, and ``/* block */``
    comments do not terminate a statement. Sufficient for standard DDL; does not
    handle dollar-quoted bodies (unused by this project's migrations).
    """
    statements: list[str] = []
    buf: list[str] = []
    in_single = in_double = in_line = in_block = False
    i, n = 0, len(sql)
    while i < n:
        ch = sql[i]
        nxt = sql[i + 1] if i + 1 < n else ""
        if in_line:
            if ch == "\n":
                in_line = False
                buf.append(ch)
            i += 1
        elif in_block:
            if ch == "*" and nxt == "/":
                in_block = False
                i += 2
            else:
                i += 1
        elif in_single:
            buf.append(ch)
            if ch == "'" and nxt == "'":
                buf.append(nxt)
                i += 2
            elif ch == "'":
                in_single = False
                i += 1
            else:
                i += 1
        elif in_double:
            buf.append(ch)
            if ch == '"':
                in_double = False
            i += 1
        elif ch == "-" and nxt == "-":
            in_line = True
            i += 2
        elif ch == "/" and nxt == "*":
            in_block = True
            i += 2
        elif ch == ";":
            if stmt := "".join(buf).strip():
                statements.append(stmt)
            buf = []
            i += 1
        else:
            if ch == "'":
                in_single = True
            elif ch == '"':
                in_double = True
            buf.append(ch)
            i += 1
    if tail := "".join(buf).strip():
        statements.append(tail)
    return statements


def ensure_database() -> None:
    """Create the target database if it does not already exist.

    CockroachDB connects lazily to a non-existent database, so we cannot detect
    absence via a failed connect. Instead we connect to a maintenance database
    and issue ``CREATE DATABASE IF NOT EXISTS`` unconditionally, tolerating the
    case where we lack privileges because the database already exists (Cloud).
    """
    settings = get_settings()
    name = target_database(settings.database_url)
    if not _IDENT_RE.match(name):
        raise ValueError(f"Refusing to create database with unsafe name: {name!r}")
    try:
        with psycopg.connect(admin_dsn(settings.database_url), autocommit=True) as conn:
            conn.execute(f'CREATE DATABASE IF NOT EXISTS "{name}"')
        log.info("ensure_database.ready", database=name)
    except psycopg.Error as exc:
        log.warning("ensure_database.skipped", database=name, reason=str(exc).splitlines()[0])


def enable_vector_indexes(conn: Connection) -> None:
    """Best-effort enable of the vector-index feature flag (older clusters)."""
    try:
        conn.execute("SET CLUSTER SETTING feature.vector_index.enabled = true")
    except psycopg.Error as exc:  # insufficient privilege on Cloud / already on
        log.info("enable_vector_indexes.skipped", reason=str(exc).splitlines()[0])


def run() -> int:
    """Apply all pending migrations. Returns the number applied."""
    ensure_database()
    migrations_dir = find_migrations_dir()
    files = sorted(migrations_dir.glob("*.sql"))
    if not files:
        log.warning("migrate.no_files", dir=str(migrations_dir))
        return 0

    applied_count = 0
    with connect() as conn:
        conn.autocommit = True
        enable_vector_indexes(conn)
        conn.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version STRING PRIMARY KEY, applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
        )
        done = {row["version"] for row in conn.execute("SELECT version FROM schema_migrations")}

        for path in files:
            version = path.stem
            if version in done:
                log.info("migrate.skip", version=version)
                continue
            log.info("migrate.apply", version=version)
            for stmt in split_statements(path.read_text(encoding="utf-8")):
                try:
                    conn.execute(stmt)
                except psycopg.Error as exc:
                    if exc.sqlstate in _DUPLICATE_SQLSTATES:
                        log.info("migrate.exists", version=version, sqlstate=exc.sqlstate)
                        continue
                    log.error("migrate.failed", version=version, error=str(exc).splitlines()[0])
                    raise
            conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (version,))
            applied_count += 1

    log.info("migrate.done", applied=applied_count, total=len(files))
    return applied_count


def main() -> None:
    configure_logging()
    try:
        run()
    except Exception as exc:
        log.error("migrate.error", error=str(exc))
        sys.exit(1)


if __name__ == "__main__":
    main()
