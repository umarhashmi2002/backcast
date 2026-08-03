# Roadmap

Deadline: **Aug 18, 2026** (CockroachDB × AWS Agentic Memory Hackathon).

## Done & validated ✅

**Foundation**
- Repo, tooling (uv, ruff, mypy `--strict`, pytest), Apache-2.0 license, GitHub Actions CI.
- CockroachDB schema across 5 idempotent migrations: incidents, immutable evidence,
  hypotheses, **bitemporal beliefs** + provenance graph, **fenced action leases**
  (`lease_generation` + heartbeat), **hash-chained** `event_ledger`, **KMS-signed ledger
  checkpoints**, semantic/procedural memory, Row-Level-TTL working memory, and the
  **counterfactual** tables (`incident_branches`, `branch_outcomes`, `simulation_runs`).
  C-SPANN vector indexes (`VECTOR(1024)`, L2). Quote/comment-aware migration runner.

**Memory engine**
- `EvidenceStore`, `BeliefStore`, `IncidentStore`, `EventLedger`, `SemanticStore`,
  `ProceduralStore`, embeddings (Bedrock Titan v2 + offline hash fallback).
- `TemporalReconstructor` — no-leak `AS OF SYSTEM TIME` reconstruction **and**
  `historical_recall` (exact-cosine cross-incident recall as of a past HLC).
- Fenced `ActionLeaseCoordinator` — claim / take-over / heartbeat / execute / complete,
  all writes gated on holder **and** fencing generation.
- `LedgerCheckpointer` — signs the ledger root hash (AWS KMS ECDSA P-256 in the cloud,
  HMAC offline) and verifies it.
- `CounterfactualService` — the **rewind → fork → compare** core: deterministic incident
  model, branch simulation, decision-regret comparator, verified-lesson promotion to
  procedural memory.

**Agent + pipelines**
- **SRE Incident Commander** — Bedrock **Nova Pro** Converse tool-loop
  (recall → beliefs → fenced action lease), with an offline scripted LLM so the whole
  loop is tested in CI without AWS.
- Evidence-preserving **consolidation** (dedup-reinforce, retrieval decay, provenance
  links; never deletes evidence) — scheduled, and it writes a signed ledger checkpoint.
- Lambda handlers: `ingest` (HMAC-verified, idempotent on `external_id`), `commander`,
  `consolidate` (EventBridge), and the `webapp` (FastAPI + Mangum).

**AWS infrastructure (CDK, Python — `BackcastStack`)**
- S3 (versioned, private), 4 container Lambdas on one image, Function URLs,
  **API Gateway** HTTP API (HMAC-verified, throttled `/incidents` ingress),
  EventBridge schedule, Secrets Manager (DSN + CA cert, webhook secret),
  CloudWatch dashboard + per-function error alarms, **KMS** signing key,
  least-privilege IAM, Bedrock invoke permissions. `cdk synth` validated.

**Web UI + demo assets**
- **React** app (Vite + TypeScript) — counterfactual "decision regret", temporal
  no-leak, and action-lease race panels — served by the FastAPI/Mangum Lambda.
- Demo scripts: `scripts/load_seed_data.py` (historical incident history for recall),
  `scripts/concurrency_demo.py` (multi-worker lease race + crash-and-resume).
- **51 tests green** (unit + live-DB integration); backend **deployed and smoke-tested**
  on AWS + CockroachDB Cloud (ingest 201 → commander recall → beliefs → fenced lease).

## Deployed ✅ (cutover complete, 2026-08-03)
- Full `BackcastStack` live on AWS: 5 Lambdas (ingest / commander / consolidate / webapp) on one
  image, API Gateway HMAC ingress, KMS signing key, EventBridge, CloudWatch, S3.
- All 5 migrations applied to the CockroachDB Cloud `retrace` cluster; DSN + CA cert in Secrets Manager.
- Smoke-tested end-to-end: signed ingest → 201, unsigned → 401, API Gateway ingress → 201,
  commander (Amazon Nova Pro) recall → observe → assess → **fenced lease** → resolve, consolidate →
  facts + procedure + **KMS-signed checkpoint** (`ECDSA_SHA_256`). Old `RetraceStack` destroyed.

## Remaining 🚧
1. **Demo video** (< 3 min) — the hosted demo URL is already live (the webapp Lambda).

## Stretch
- MCP-server-driven read-only "explain this incident" tool.
- Grafana/console view of the belief-revision timeline.
- Belief calibration metrics (were high-confidence beliefs correct?).
- S3 Object Lock export of signed ledger checkpoints (WORM retention).
