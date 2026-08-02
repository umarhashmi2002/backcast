#!/usr/bin/env python
"""Seed historical, resolved incidents so cross-incident recall has something to find.

Each seed incident is recorded with immutable evidence, a supported belief, and a
resolution, then consolidated into semantic + procedural memory — exactly as the
live system would after closing a real incident. Idempotent: re-running skips
incidents that already exist (by external_id).

Run:  make seed                                  (offline hash embeddings, local DB)
      uv run python scripts/load_seed_data.py --bedrock   (Titan embeddings, e.g. Cloud)

Note: seed with the SAME embedder the reader uses — hash for local, --bedrock for
a Bedrock-backed deployment — or the vectors won't be comparable.
"""

from __future__ import annotations

import argparse

from backcast.config import Settings, get_settings
from backcast.memory import MemoryEngine
from backcast.memory.models import Evidence, EvidenceKind, IncidentStatus, Severity

SEED_INCIDENTS = [
    {
        "external_id": "seed-payments-pool",
        "title": "payments-api 5xx from DB connection pool exhaustion",
        "service": "payments-api",
        "evidence": [
            (
                EvidenceKind.metric,
                "payments-api error rate 6%; DB connection pool at 98% utilization",
            ),
            (EvidenceKind.deploy, "deploy v1.9.0 lowered the connection pool max size"),
        ],
        "hypothesis": "a deploy shrank the DB connection pool, causing exhaustion under load",
        "resolution": "Reverted the pool-size change and raised max connections to 200",
    },
    {
        "external_id": "seed-checkout-oom",
        "title": "checkout-service pods OOMKilled during peak",
        "service": "checkout-service",
        "evidence": [
            (
                EvidenceKind.metric,
                "checkout-service memory climbing to the container limit, then restart",
            ),
            (EvidenceKind.log, "OOMKilled events on checkout-service pods every ~10 minutes"),
        ],
        "hypothesis": "a memory leak in the cart cache exhausts the container limit",
        "resolution": "Raised memory limit and shipped a fix that bounds the in-memory cart cache",
    },
    {
        "external_id": "seed-auth-cert",
        "title": "auth-service TLS handshake failures",
        "service": "auth-service",
        "evidence": [
            (EvidenceKind.log, "auth-service clients failing with certificate expired errors"),
            (EvidenceKind.topology, "upstream cert notAfter timestamp is in the past"),
        ],
        "hypothesis": "the auth-service serving certificate expired and was not rotated",
        "resolution": "Rotated the TLS certificate and enabled automated cert renewal",
    },
    {
        "external_id": "seed-search-index",
        "title": "search-service latency spike after index change",
        "service": "search-service",
        "evidence": [
            (
                EvidenceKind.trace,
                "search-service p99 latency jumped 8x; full table scans in query plans",
            ),
            (EvidenceKind.deploy, "migration dropped a composite index the hot query relied on"),
        ],
        "hypothesis": "a migration dropped an index the primary search query depended on",
        "resolution": "Recreated the composite index and added a guard to migration review",
    },
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed historical resolved incidents.")
    parser.add_argument("--org", default="demo", help="Tenant id to seed (default: demo).")
    parser.add_argument("--bedrock", action="store_true", help="Use Bedrock Titan embeddings.")
    args = parser.parse_args()

    settings = get_settings() if args.bedrock else Settings(embedding_model_id="hash")
    engine = MemoryEngine(settings=settings)
    org = args.org
    seeded = 0

    print(f"Seeding org '{org}' ({'Bedrock Titan' if args.bedrock else 'offline hash'} embeddings)")
    try:
        for spec in SEED_INCIDENTS:
            row, created = engine.incidents.upsert(
                org,
                str(spec["external_id"]),
                title=str(spec["title"]),
                service=str(spec["service"]),
                severity=Severity.sev2,
            )
            incident_id = row["id"]
            if not created:
                print(f"  skip (exists): {spec['title']}")
                continue

            for kind, content in spec["evidence"]:
                engine.evidence.record(
                    Evidence(org_id=org, incident_id=incident_id, kind=kind, content=content)
                )
            hypothesis = engine.beliefs.create_hypothesis(org, incident_id, str(spec["hypothesis"]))
            assert hypothesis.id is not None
            engine.beliefs.set_belief(
                org, incident_id, hypothesis.id, 0.88, rationale="root cause confirmed at the time"
            )
            engine.incidents.set_status(
                incident_id, IncidentStatus.resolved, resolution=str(spec["resolution"])
            )
            report = engine.consolidator.consolidate_incident(org, incident_id)
            engine.incidents.mark_consolidated(incident_id)
            seeded += 1
            print(
                f"  seeded: {spec['title']}  "
                f"(facts={report.facts_created}, procedure={report.procedure_created})"
            )

        print(f"\nDone — {seeded} new incident(s) consolidated into long-term memory.")
        hits = engine.procedural.recall(
            org, "database connection pool exhausted after a deploy", top_k=1
        )
        if hits:
            print(f"Sanity recall → {hits[0].name}: {hits[0].steps[:60]}")
    finally:
        engine.close()


if __name__ == "__main__":
    main()
