#!/usr/bin/env python
"""Concurrency + crash-safety demo for Retrace's action leases.

Two things a RAG cache fundamentally cannot do, shown live against CockroachDB:

  1. RACE      — N workers receive the same alert and race to remediate.
                 Exactly ONE wins the transactional action lease; the rest stand down.
  2. CRASH     — the winner applies the fix, then crashes before recording completion.
                 A standby takes over the EXPIRED lease and, because the effect is keyed
                 by the preserved idempotency key, the rollback still runs exactly once.

Run:  make race-demo   (or)   uv run python scripts/concurrency_demo.py [n_workers]
Requires a running database (make db-up). Uses offline embeddings; no AWS needed.
"""

from __future__ import annotations

import sys
import time
from concurrent.futures import ThreadPoolExecutor
from uuid import UUID, uuid4

from retrace.config import Settings
from retrace.db.connection import connect
from retrace.memory import HashEmbedder, MemoryEngine

SETTINGS = Settings(embedding_model_id="hash")
DEMO_TABLE = "demo_rollback_effects"
ORG = f"race-{uuid4().hex[:8]}"


def _rule(title: str) -> None:
    print(f"\n\033[1;36m{'─' * 72}\n{title}\n{'─' * 72}\033[0m")


def _engine() -> MemoryEngine:
    return MemoryEngine(
        conn=connect(SETTINGS.database_url),
        embedder=HashEmbedder(SETTINGS.embedding_dims),
        settings=SETTINGS,
    )


def _ensure_effects_table(engine: MemoryEngine) -> None:
    engine.conn.execute(
        f"CREATE TABLE IF NOT EXISTS {DEMO_TABLE} "
        "(idempotency_key STRING PRIMARY KEY, applied_by STRING NOT NULL, "
        "applied_at TIMESTAMPTZ NOT NULL DEFAULT now())"
    )


def _apply_rollback(engine: MemoryEngine, idempotency_key: str, worker: str) -> bool:
    """The external effect, guarded by its idempotency key — applying twice is a no-op."""
    row = engine.conn.execute(
        f"INSERT INTO {DEMO_TABLE} (idempotency_key, applied_by) VALUES (%s, %s) "
        "ON CONFLICT (idempotency_key) DO NOTHING RETURNING applied_by",
        (idempotency_key, worker),
    ).fetchone()
    return row is not None


def race_demo(incident_id: UUID, n_workers: int) -> None:
    _rule(f"RACE · {n_workers} workers propose the same rollback simultaneously")
    action_key = f"rollback:payments-api:v2.4.1:{incident_id}"

    def worker(i: int) -> bool:
        engine = _engine()
        try:
            return engine.leases.claim(ORG, incident_id, action_key, holder=f"worker-{i}").won
        finally:
            engine.close()

    with ThreadPoolExecutor(max_workers=n_workers) as pool:
        outcomes = list(pool.map(worker, range(n_workers)))

    winners = sum(outcomes)
    print(f"  workers that attempted : {n_workers}")
    print(f"  workers that won lease : \033[1m{winners}\033[0m  (must be exactly 1)")
    assert winners == 1, "action lease failed to enforce single ownership!"


def crash_resume_demo(incident_id: UUID) -> None:
    _rule("CRASH · winner dies mid-rollback; standby resumes without double-executing")
    action_key = f"rollback:crash:{uuid4().hex[:8]}"

    # Worker A wins with a short lease, applies the effect, then crashes before completing.
    a = _engine()
    claim = a.leases.claim(ORG, incident_id, action_key, holder="worker-A", ttl_seconds=2)
    assert claim.won and claim.lease_id and claim.idempotency_key
    a.leases.mark_executing(claim.lease_id)
    applied_a = _apply_rollback(a, claim.idempotency_key, "worker-A")
    print(
        f"  worker-A won lease, applied rollback ({applied_a}), then \033[1mCRASHED\033[0m before completing"
    )
    a.close()  # simulate crash: connection lost, lease left in 'executing'

    print("  ...lease expires...")
    time.sleep(3)

    # Standby worker B takes over the expired lease and finishes the job idempotently.
    b = _engine()
    takeover = b.leases.take_over_if_expired(ORG, action_key, holder="worker-B", ttl_seconds=60)
    assert takeover is not None and takeover.lease_id and takeover.idempotency_key
    applied_b = _apply_rollback(b, takeover.idempotency_key, "worker-B")
    b.leases.complete(takeover.lease_id, {"resumed_by": "worker-B"})
    executions = b.conn.execute(
        f"SELECT count(*) AS c FROM {DEMO_TABLE} WHERE idempotency_key = %s",
        (claim.idempotency_key,),
    ).fetchone()
    count = int(executions["c"]) if executions else -1
    print(
        f"  worker-B took over the expired lease; re-applied rollback: {applied_b} (False = blocked)"
    )
    print(f"  rollback executed \033[1mexactly {count} time(s)\033[0m across the crash")
    assert count == 1, "idempotency failed to prevent double execution!"
    b.close()


def main() -> None:
    n_workers = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    setup = _engine()
    _ensure_effects_table(setup)
    incident_id: UUID = setup.incidents.create(ORG, "payments-api 5xx spike", "payments-api")["id"]
    setup.close()

    print(f"\n\033[1mRetrace — action lease concurrency + crash safety\033[0m  (org={ORG})")
    race_demo(incident_id, n_workers)
    crash_resume_demo(incident_id)
    print(
        "\n\033[1;32mMemory governed the agents: one action, once — even under races and crashes.\033[0m\n"
    )


if __name__ == "__main__":
    main()
