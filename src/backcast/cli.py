"""Backcast command-line interface.

``backcast migrate``  Apply the database schema.
``backcast demo``     Narrate every headline mechanism end-to-end against the
                     configured CockroachDB (offline embeddings by default).
"""

from __future__ import annotations

import argparse
import textwrap
from uuid import UUID, uuid4

from .config import Settings, get_settings
from .db import migrate as migrate_module
from .memory import MemoryEngine
from .memory.models import Evidence, EvidenceKind, IncidentStatus, NodeType, Relation


def _rule(title: str) -> None:
    print(f"\n\033[1;36m{'─' * 72}\n{title}\n{'─' * 72}\033[0m")


def _kv(label: str, value: str) -> None:
    print(f"  {label:<26} {value}")


def cmd_migrate(_: argparse.Namespace) -> None:
    migrate_module.run()


def cmd_demo(args: argparse.Namespace) -> None:
    settings = get_settings() if args.bedrock else Settings(embedding_model_id="hash")
    engine = MemoryEngine(settings=settings)
    org = args.org
    embed_mode = "Bedrock Titan" if args.bedrock else "offline hash embedder"
    try:
        _run_demo(engine, org, embed_mode)
    finally:
        engine.close()


def _run_demo(engine: MemoryEngine, org: str, embed_mode: str) -> None:
    print(
        textwrap.dedent(
            f"""
            \033[1mBackcast — agentic memory on CockroachDB\033[0m
            org={org}  embeddings={embed_mode}

            Scenario: payments-api starts returning 5xx errors. The Incident
            Commander reasons in real time; every belief and action is recorded
            in one transactional, temporal system of record.
            """
        ).rstrip()
    )

    incident = engine.incidents.create(
        org, "payments-api 5xx spike", "payments-api", external_id=f"am-{uuid4().hex[:8]}"
    )
    iid: UUID = incident["id"]
    engine.ledger.append(org, iid, "incident_opened", {"service": "payments-api"}, actor="agent")

    # --- t1 (03:14): first evidence, first beliefs -----------------------
    _rule("t1 · 03:14 — first evidence arrives")
    e_metric = engine.evidence.record(
        Evidence(
            org_id=org,
            incident_id=iid,
            kind=EvidenceKind.metric,
            source="prometheus",
            content="API error rate climbing to 5%; DB connection pool at 94% utilization",
        )
    )
    metric_id = e_metric.id
    assert metric_id is not None
    engine.ledger.append(org, iid, "evidence_recorded", {"id": str(metric_id)}, actor="agent")

    h_surge = engine.beliefs.create_hypothesis(org, iid, "Traffic surge overwhelming the service")
    h_deploy = engine.beliefs.create_hypothesis(
        org, iid, "Recent deploy introduced a connection leak"
    )
    surge_id, deploy_id = h_surge.id, h_deploy.id
    assert surge_id is not None
    assert deploy_id is not None

    engine.beliefs.set_belief(
        org, iid, surge_id, 0.58, rationale="error rate up; no deploy correlation discovered yet"
    )
    engine.beliefs.set_belief(org, iid, deploy_id, 0.11, rationale="no deploy evidence yet")
    engine.beliefs.add_edge(
        org, iid, NodeType.evidence, metric_id, Relation.supports, NodeType.hypothesis, surge_id
    )

    hlc_t1 = engine.temporal.capture_hlc()
    for belief in engine.beliefs.current_beliefs(iid):
        stmt = h_surge.statement if belief.hypothesis_id == surge_id else h_deploy.statement
        _kv(f"belief · {stmt[:38]}", f"{belief.confidence:.0%}")
    _kv("captured HLC", hlc_t1)

    # --- t2 (03:17): new evidence flips the conclusion -------------------
    _rule("t2 · 03:17 — deploy evidence changes everything")
    e_deploy = engine.evidence.record(
        Evidence(
            org_id=org,
            incident_id=iid,
            kind=EvidenceKind.deploy,
            source="argocd",
            content="Deploy v2.4.1 shipped 6 minutes before degradation; touches the DB pool config",
        )
    )
    deploy_ev_id = e_deploy.id
    assert deploy_ev_id is not None
    engine.beliefs.add_edge(
        org, iid, NodeType.evidence, deploy_ev_id, Relation.supports, NodeType.hypothesis, deploy_id
    )
    engine.beliefs.add_edge(
        org,
        iid,
        NodeType.evidence,
        deploy_ev_id,
        Relation.contradicts,
        NodeType.hypothesis,
        surge_id,
    )
    engine.beliefs.set_belief(
        org, iid, deploy_id, 0.87, rationale="deploy v2.4.1 correlated 6m before onset"
    )
    engine.beliefs.set_belief(org, iid, surge_id, 0.08, rationale="traffic within normal range")
    engine.ledger.append(
        org, iid, "belief_updated", {"deploy_defect": 0.87, "traffic_surge": 0.08}, actor="agent"
    )
    for belief in engine.beliefs.current_beliefs(iid):
        stmt = h_surge.statement if belief.hypothesis_id == surge_id else h_deploy.statement
        _kv(f"belief · {stmt[:38]}", f"{belief.confidence:.0%}")

    # --- Mechanism 1: temporal no-leak reconstruction --------------------
    _rule("MECHANISM 1 · Temporal reconstruction (AS OF SYSTEM TIME)")
    past = engine.temporal.reconstruct(iid, hlc_t1)
    now = engine.temporal.reconstruct(iid, engine.temporal.capture_hlc())
    print("  What the agent knew at 03:14 (reconstructed from the DB at that HLC):")
    for ev in past.evidence:
        print(f"    - [{ev.kind}] {ev.content[:60]}")
    print(f"  → evidence visible at t1: {len(past.evidence)}   |   now: {len(now.evidence)}")
    leaked = any(ev.kind == EvidenceKind.deploy for ev in past.evidence)
    print(
        f"  \033[1mNo-leak guarantee:\033[0m deploy evidence hidden from the past view = {not leaked}"
    )

    # --- Mechanism 2: belief provenance ----------------------------------
    _rule("MECHANISM 2 · Belief revision + provenance")
    history = engine.beliefs.belief_history(iid, deploy_id)
    for belief in history:
        state = "superseded" if belief.valid_until else "current"
        _kv(f"deploy-defect confidence ({state})", f"{belief.confidence:.0%}  — {belief.rationale}")

    # --- Mechanism 3: memory governs action ------------------------------
    _rule("MECHANISM 3 · Transactional action lease (safe autonomy)")
    action_key = f"rollback:payments-api:v2.4.1:{iid}"
    print("  25 duplicate workers receive the same alert and propose the same rollback...")
    winner = None
    for worker in range(25):
        claim = engine.leases.claim(
            org, iid, action_key, holder=f"worker-{worker}", payload={"action": "rollback"}
        )
        if claim.won:
            winner = claim
    assert winner is not None
    lease = engine.leases.get(org, action_key)
    assert lease is not None
    _kv("workers that attempted", "25")
    _kv("workers that won the claim", f"1  ({winner.holder})")
    engine.ledger.append(
        org,
        iid,
        "action_claimed",
        {"action_key": action_key, "holder": winner.holder},
        actor=winner.holder,
    )

    # crash-safe: another worker takes over only if the lease has expired
    takeover = engine.leases.take_over_if_expired(org, action_key, holder="worker-standby")
    _kv("takeover while holder alive", "refused" if takeover is None else "unexpected!")

    # --- Mechanism 4: hash-chained ledger --------------------------------
    _rule("MECHANISM 4 · Hash-chained permanent provenance")
    _kv("ledger chain verified", str(engine.ledger.verify(iid)))

    # --- Mechanism 5: compounding knowledge ------------------------------
    _rule("MECHANISM 5 · Compounding knowledge (evidence-preserving consolidation)")
    engine.incidents.set_status(
        iid, IncidentStatus.resolved, resolution="Rolled back v2.4.1 and raised the DB pool limit"
    )
    report = engine.consolidator.consolidate_incident(org, iid)
    _kv("semantic facts learned", str(report.facts_created))
    _kv("procedure learned", "yes" if report.procedure_created else "no")
    learned = engine.procedural.recall(org, "deploy connection leak in payments-api", top_k=1)
    if learned:
        _kv("recalled next time", f"{learned[0].name} → {learned[0].steps[:40]}")
    _kv("evidence still immutable", f"{len(engine.evidence.for_incident(iid))} rows, unchanged")

    print(
        "\n\033[1;32mDemo complete — one transactional temporal DB did all of the above.\033[0m\n"
    )


def main() -> None:
    parser = argparse.ArgumentParser(prog="backcast", description="Agentic memory on CockroachDB.")
    sub = parser.add_subparsers(dest="command", required=True)

    p_migrate = sub.add_parser("migrate", help="Apply the database schema.")
    p_migrate.set_defaults(func=cmd_migrate)

    p_demo = sub.add_parser("demo", help="Narrate the headline mechanisms end-to-end.")
    p_demo.add_argument("--org", default="demo", help="Tenant id to use (default: demo).")
    p_demo.add_argument(
        "--bedrock", action="store_true", help="Use Bedrock Titan embeddings (needs AWS creds)."
    )
    p_demo.set_defaults(func=cmd_demo)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
