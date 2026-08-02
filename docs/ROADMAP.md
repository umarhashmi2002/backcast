# Roadmap

Deadline: **Aug 18, 2026** (CockroachDB × AWS Agentic Memory Hackathon).

## Done & validated ✅
- Repo, tooling (uv, ruff, mypy `--strict`, pytest), Apache-2.0, CI.
- CockroachDB schema: incidents, immutable evidence, hypotheses, bitemporal beliefs,
  provenance graph, action leases, hash-chained ledger, semantic/procedural memory,
  Row-Level-TTL working memory. C-SPANN vector indexes. Idempotent migration runner.
- Memory engine: `EvidenceStore`, `BeliefStore`, `TemporalReconstructor`, `ActionLeaseCoordinator`,
  `EventLedger`, `IncidentStore`, embeddings (Bedrock Titan + offline hash).
- **All five headline mechanisms proven** by tests + `backcast demo` on CockroachDB 25.2.
- **SRE Incident Commander agent** — Bedrock Converse tool-loop (recall → beliefs → action lease),
  with an offline scripted LLM so the whole loop is tested in CI without AWS.
- **Long-term memory + evidence-preserving consolidation** — `SemanticStore`, `ProceduralStore`, and
  a gated `Consolidator` (dedup-reinforce, retrieval decay, provenance links; never deletes evidence).
- **26 tests green** (unit + live-DB integration); CI workflow in `.github/`.

## In progress 🚧
1. **Lambda handlers** — `ingest` (alert → incident, idempotent on `external_id`), `commander`
   (agent turn), `consolidate` (EventBridge schedule).
2. **AWS CDK (Python)** — S3, Lambda, API Gateway, EventBridge, Secrets Manager, CloudWatch,
   least-privilege IAM, Bedrock invoke permissions.
3. **Seed data** — `scripts/load_seed_data.py` (historical resolved incidents for cross-incident recall).
4. **Concurrency demo** — multi-process action-lease race + crash-and-resume script for the video.
5. **Signed incident packages** — export closed-incident provenance bundles to S3.
6. **Demo video** (< 3 min) + hosted demo URL.

## Stretch
- MCP-server-driven read-only "explain this incident" tool.
- Grafana/console view of the belief-revision timeline.
- Belief calibration metrics (were high-confidence beliefs correct?).
