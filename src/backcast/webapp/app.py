"""FastAPI app for the Backcast interactive demo."""

from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from mangum import Mangum

from ..agent import BedrockLLM, IncidentCommander
from ..api.runtime import get_database_url
from ..config import Settings
from ..db.connection import connect
from ..memory import HashEmbedder, MemoryEngine
from ..memory.models import Belief, Evidence, EvidenceKind, IncidentStatus
from ..simulation.comparator import BranchResult, compare
from ..simulation.model import DeterministicIncidentModel
from ..simulation.scenarios import SCENARIOS, RemediationEffect, Scenario

_STATIC = Path(__file__).parent / "static"
_SETTINGS = Settings(embedding_model_id="hash")


def _find_openapi() -> Path | None:
    """Locate docs/openapi.yaml in a source checkout or the Lambda image."""
    task_root = os.environ.get("LAMBDA_TASK_ROOT")
    candidates = [
        Path(__file__).resolve().parents[3] / "docs" / "openapi.yaml",  # source checkout
        *( [Path(task_root) / "docs" / "openapi.yaml"] if task_root else [] ),  # image bundle
    ]
    return next((p for p in candidates if p.is_file()), None)

app = FastAPI(title="Backcast", description="Temporal decision laboratory for on-call.")
handler = Mangum(app)  # AWS Lambda entry point (API Gateway / Function URL)

# The Vite/React build emits index.html + assets/ into this dir; serve the assets.
if (_STATIC / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC / "assets"), name="assets")


def _engine() -> MemoryEngine:
    # get_database_url() reads the Secrets Manager DSN (+ CA cert) in Lambda, or
    # falls back to the local DSN for `make web`. Hash embeddings keep it AWS-free.
    return MemoryEngine(
        conn=connect(get_database_url()),
        embedder=HashEmbedder(_SETTINGS.embedding_dims),
        settings=_SETTINGS,
    )


@app.get("/")
def index() -> FileResponse:
    return FileResponse(_STATIC / "index.html")


@app.get("/openapi.yaml", include_in_schema=False)
def openapi_yaml() -> FileResponse:
    """Serve the hand-authored OpenAPI 3.0 spec (Swagger UI is at /docs)."""
    spec = _find_openapi()
    if spec is None:
        raise HTTPException(status_code=404, detail="openapi.yaml not bundled in this image")
    return FileResponse(spec, media_type="application/yaml")


@app.get("/health")
def health() -> dict[str, str]:
    engine = _engine()
    try:
        engine.conn.execute("SELECT 1")
        return {"status": "ok"}
    finally:
        engine.close()


def _branch_dict(b: BranchResult, best_id: object) -> dict[str, Any]:
    return {
        "label": b.label,
        "remediations": b.remediations,
        "score": b.outcome.score,
        "recovered": b.outcome.recovered,
        "recurred": b.outcome.recurred,
        "time_to_recovery_s": b.outcome.time_to_recovery_s,
        "risk": b.outcome.risk,
        "cost": b.outcome.cost,
        "unnecessary_actions": b.outcome.unnecessary_actions,
        "is_actual": b.is_actual,
        "is_best": b.branch_id == best_id,
    }


@app.get("/api/scenarios")
def scenarios() -> dict[str, Any]:
    """The built-in incident library — each with a hidden true cause + candidate remediations."""
    return {
        "scenarios": [
            {
                "key": s.key,
                "true_cause": s.true_cause,
                "description": s.description,
                "remediations": {
                    n: {
                        "fixes": e.fixes,
                        "relieves": e.relieves,
                        "recovery_seconds": e.recovery_seconds,
                        "risk": e.risk,
                        "cost": e.cost,
                    }
                    for n, e in s.remediations.items()
                },
            }
            for s in SCENARIOS.values()
        ]
    }


@app.post("/api/counterfactual")
def counterfactual(org: str = "demo", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Rewind → fork → simulate → compare → learn, live. Pick a library scenario + the action taken."""
    payload = payload or {}
    scenario_key = str(payload.get("scenario_key") or "db_pool_exhaustion")
    if scenario_key not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario '{scenario_key}'")
    scenario = SCENARIOS[scenario_key]
    chosen = payload.get("actual_remediation")
    default_actual = "restart-service" if "restart-service" in scenario.remediations else next(iter(scenario.remediations))
    actual = [str(chosen)] if chosen else [default_actual]
    if actual[0] not in scenario.remediations:
        raise HTTPException(status_code=400, detail=f"'{actual[0]}' is not a remediation of '{scenario_key}'")

    engine = _engine()
    try:
        iid = engine.incidents.create(
            org, scenario.description, "payments-api",
            external_id=f"cf-{uuid4().hex[:8]}", scenario=scenario_key,
        )["id"]
        engine.evidence.record(Evidence(
            org_id=org, incident_id=iid, kind=EvidenceKind.metric, content=scenario.description,
        ))
        hypothesis = engine.beliefs.create_hypothesis(org, iid, scenario.true_cause)
        assert hypothesis.id is not None
        engine.beliefs.set_belief(org, iid, hypothesis.id, 0.7, rationale="leading hypothesis at onset")
        fork_hlc = engine.temporal.capture_hlc()
        engine.incidents.set_status(iid, IncidentStatus.resolved, resolution=f"applied {actual[0]}")

        report = engine.counterfactual.run(org, iid, actual_remediations=actual, forked_at_hlc=fork_hlc)
        ordered = sorted(report.branches, key=lambda b: b.outcome.score, reverse=True)
        return {
            "incident_id": str(iid),
            "scenario": report.scenario,
            "actual_remediation": actual[0],
            "forked_at_hlc": report.forked_at_hlc,
            "branches": [_branch_dict(b, report.best.branch_id) for b in ordered],
            "best_label": report.best.label,
            "decision_regret": report.decision_regret,
            "lesson": report.lesson,
            "ledger_verified": engine.ledger.verify(iid),
        }
    finally:
        engine.close()


@app.post("/api/simulate")
def simulate(payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Build-your-own incident: a custom true cause + remediations → live decision regret (no DB)."""
    payload = payload or {}
    true_cause = str(payload.get("true_cause") or "").strip()
    rem_specs = payload.get("remediations")
    if not true_cause or not isinstance(rem_specs, dict) or not rem_specs:
        raise HTTPException(status_code=400, detail="true_cause and at least one remediation are required")

    remediations: dict[str, RemediationEffect] = {}
    for name, spec in rem_specs.items():
        s = spec if isinstance(spec, dict) else {}
        remediations[str(name)] = RemediationEffect(
            fixes=bool(s.get("fixes", False)),
            relieves=bool(s.get("relieves", False)),
            recovery_seconds=float(s.get("recovery_seconds", 60.0)),
            risk=float(s.get("risk", 0.1)),
            cost=float(s.get("cost", 1.0)),
        )
    scenario = Scenario(
        key="custom", true_cause=true_cause,
        description=str(payload.get("description") or true_cause), remediations=remediations,
    )
    raw_actual = payload.get("actual") or []
    actual = [str(a) for a in raw_actual] if isinstance(raw_actual, list) else [str(raw_actual)]
    actual = [a for a in actual if a in remediations] or [next(iter(remediations))]

    model = DeterministicIncidentModel()
    branches: list[BranchResult] = [
        BranchResult("actual", "actual", actual, is_actual=True, outcome=model.simulate(scenario, actual))
    ]
    for name in remediations:
        branches.append(
            BranchResult(name, f"fork:{name}", [name], is_actual=False, outcome=model.simulate(scenario, [name]))
        )
    comparison = compare(branches)
    best = comparison.best
    lesson = None
    if best.branch_id != "actual" and best.outcome.recovered:
        lesson = (
            f"For '{true_cause}', the best simulation-backed remediation is "
            f"'{' then '.join(best.remediations)}' (simulated score {best.outcome.score})."
        )
    return {
        "scenario": "custom",
        "true_cause": true_cause,
        "actual_remediation": " then ".join(actual),
        "branches": [_branch_dict(b, best.branch_id) for b in comparison.ranked],
        "best_label": best.label,
        "decision_regret": comparison.decision_regret,
        "lesson": lesson,
    }


@app.post("/api/incident")
def incident(org: str = "demo") -> dict[str, Any]:
    """Belief revision + temporal no-leak reconstruction, live."""
    engine = _engine()
    try:
        iid = engine.incidents.create(
            org, "payments-api 5xx spike", "payments-api", external_id=f"inc-{uuid4().hex[:8]}"
        )["id"]
        engine.ledger.append(org, iid, "incident_opened", {"service": "payments-api"}, actor="agent")

        engine.evidence.record(Evidence(
            org_id=org, incident_id=iid, kind=EvidenceKind.metric, source="prometheus",
            content="API error rate climbing to 5%; DB connection pool at 94%",
        ))
        surge = engine.beliefs.create_hypothesis(org, iid, "Traffic surge overwhelming the service")
        deploy = engine.beliefs.create_hypothesis(org, iid, "Recent deploy introduced a connection leak")
        assert surge.id is not None
        assert deploy.id is not None
        engine.beliefs.set_belief(org, iid, surge.id, 0.58, rationale="error rate up; no deploy link yet")
        engine.beliefs.set_belief(org, iid, deploy.id, 0.11, rationale="no deploy evidence yet")
        t1_hlc = engine.temporal.capture_hlc()

        engine.evidence.record(Evidence(
            org_id=org, incident_id=iid, kind=EvidenceKind.deploy, source="argocd",
            content="Deploy v2.4.1 shipped 6 minutes before degradation; touches the DB pool config",
        ))
        engine.beliefs.set_belief(org, iid, deploy.id, 0.87, rationale="deploy v2.4.1 correlated 6m before")
        engine.beliefs.set_belief(org, iid, surge.id, 0.08, rationale="traffic within normal range")

        past = engine.temporal.reconstruct(iid, t1_hlc)
        now = engine.temporal.reconstruct(iid, engine.temporal.capture_hlc())
        history = engine.beliefs.belief_history(iid, deploy.id)

        def conf(beliefs: list[Belief], hyp_id: object) -> float:
            return next((b.confidence for b in beliefs if str(b.hypothesis_id) == str(hyp_id)), 0.0)

        return {
            "incident_id": str(iid),
            "t1_hlc": t1_hlc,
            "surge_hypothesis": surge.statement,
            "deploy_hypothesis": deploy.statement,
            "at_t1": {
                "evidence": [{"kind": str(e.kind), "content": e.content} for e in past.evidence],
                "surge": conf(past.beliefs, surge.id),
                "deploy": conf(past.beliefs, deploy.id),
            },
            "now": {
                "evidence": [{"kind": str(e.kind), "content": e.content} for e in now.evidence],
                "surge": conf(now.beliefs, surge.id),
                "deploy": conf(now.beliefs, deploy.id),
            },
            "no_leak": all(e.kind != EvidenceKind.deploy for e in past.evidence),
            "deploy_belief_history": [
                {"confidence": b.confidence, "current": b.valid_until is None} for b in history
            ],
            "ledger_verified": engine.ledger.verify(iid),
        }
    finally:
        engine.close()


@app.post("/api/race")
def race(org: str = "demo", workers: int = 20) -> dict[str, Any]:
    """Concurrency + fencing: N workers race; a revived stale worker is fenced out."""
    workers = max(2, min(workers, 50))
    org = f"{org}-race-{uuid4().hex[:6]}"
    setup = _engine()
    setup.conn.execute(
        "CREATE TABLE IF NOT EXISTS demo_web_effects "
        "(idempotency_key STRING PRIMARY KEY, applied_by STRING NOT NULL)"
    )
    iid = setup.incidents.create(org, "payments-api 5xx", "payments-api")["id"]
    setup.close()
    action_key = f"rollback:{iid}"

    def attempt(i: int) -> bool:
        eng = _engine()
        try:
            return eng.leases.claim(org, iid, action_key, holder=f"worker-{i}").won
        finally:
            eng.close()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        wins = sum(pool.map(attempt, range(workers)))

    # Crash + fenced takeover on a separate action key.
    crash_key = f"crash-rollback:{iid}"
    idem = uuid4().hex

    def apply_effect(eng: MemoryEngine, worker: str) -> bool:
        row = eng.conn.execute(
            "INSERT INTO demo_web_effects (idempotency_key, applied_by) VALUES (%s, %s) "
            "ON CONFLICT (idempotency_key) DO NOTHING RETURNING applied_by",
            (idem, worker),
        ).fetchone()
        return row is not None

    a = _engine()
    claim = a.leases.claim(org, iid, crash_key, holder="worker-A", ttl_seconds=1, idempotency_key=idem)
    assert claim.lease_id is not None
    a.leases.mark_executing(claim.lease_id, "worker-A", claim.lease_generation)
    apply_effect(a, "worker-A")
    a.close()  # crash
    import time

    time.sleep(1.3)
    b = _engine()
    takeover = b.leases.take_over_if_expired(org, crash_key, holder="worker-B")
    assert takeover is not None
    assert takeover.lease_id is not None
    apply_effect(b, "worker-B")
    completed_b = b.leases.complete(takeover.lease_id, "worker-B", takeover.lease_generation)
    a2 = _engine()
    revived_ok = a2.leases.complete(claim.lease_id, "worker-A", claim.lease_generation)
    count = b.conn.execute(
        "SELECT count(*) AS n FROM demo_web_effects WHERE idempotency_key = %s", (idem,)
    ).fetchone()
    executions = int(count["n"]) if count else -1
    a2.close()
    b.close()

    return {
        "workers": workers,
        "winners": wins,
        "crash_takeover_generation": takeover.lease_generation,
        "taker_completed": completed_b,
        "revived_stale_worker_accepted": revived_ok,
        "external_effect_executions": executions,
    }


@app.post("/api/agent")
def agent_turn(org: str = "demo", payload: dict[str, Any] | None = None) -> dict[str, Any]:
    """Live Incident Commander turn (Amazon Nova Pro): type an alert, watch the agent reason + act."""
    payload = payload or {}
    signal = str(payload.get("signal") or "").strip()
    if not signal:
        raise HTTPException(status_code=400, detail="signal is required")
    scenario_key = payload.get("scenario_key")
    if scenario_key and str(scenario_key) not in SCENARIOS:
        raise HTTPException(status_code=400, detail=f"unknown scenario '{scenario_key}'")

    engine = _engine()
    try:
        iid = engine.incidents.create(
            org, signal[:80], "user-incident",
            external_id=f"ag-{uuid4().hex[:8]}",
            scenario=str(scenario_key) if scenario_key else None,
        )["id"]
        engine.ledger.append(org, iid, "incident_opened", {"signal": signal[:200]}, actor="webapp")

        commander = IncidentCommander(engine, BedrockLLM())
        result = commander.handle(org, iid, signal, worker_id="webapp-agent")

        rows = engine.conn.execute(
            "SELECT h.statement, b.confidence FROM beliefs b JOIN hypotheses h ON h.id = b.hypothesis_id "
            "WHERE b.incident_id = %s AND b.valid_until IS NULL ORDER BY b.confidence DESC",
            (iid,),
        ).fetchall()
        beliefs = [{"statement": r["statement"], "confidence": float(r["confidence"])} for r in rows]

        return {
            "incident_id": str(iid),
            "steps": result.steps,
            "tool_calls": result.tool_calls,
            "claimed_action": result.claimed_action,
            "summary": result.final_text,
            "beliefs": beliefs,
            "ledger_verified": engine.ledger.verify(iid),
        }
    finally:
        engine.close()
