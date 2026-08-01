# Roadmap

Deadline: **Aug 18, 2026** (CockroachDB × AWS Agentic Memory Hackathon).

## Done & validated ✅
- Repo, tooling (uv, ruff, mypy `--strict`, pytest), Apache-2.0, CI.
- CockroachDB schema: incidents, immutable evidence, hypotheses, bitemporal beliefs,
  provenance graph, action leases, hash-chained ledger, semantic/procedural memory,
  Row-Level-TTL working memory. C-SPANN vector indexes. Idempotent migration runner.
- Memory engine: `EvidenceStore`, `BeliefStore`, `TemporalReconstructor`, `ActionLeaseCoordinator`,
  `EventLedger`, `IncidentStore`, embeddings (Bedrock Titan + offline hash).
- **All five headline mechanisms proven** by 13 tests + `retrace demo` on CockroachDB 25.2.

## In progress 🚧
1. **Long-term memory + consolidation** — `SemanticStore`, `ProceduralStore`, and the gated,
   evidence-preserving `Consolidator` (distill closed incidents → versioned facts + procedures,
   linked to immutable evidence; decay retrieval score; never delete evidence).
2. **SRE Incident Commander agent** — Bedrock Claude reasoning loop with tools (recall evidence,
   form/revise beliefs, claim + execute remediation via the action lease).
3. **Lambda handlers** — `ingest` (alert → incident, idempotent on `external_id`), `commander`
   (agent turn), `consolidate` (EventBridge schedule).
4. **AWS CDK (Python)** — S3, Lambda, API Gateway, EventBridge, Secrets Manager, CloudWatch,
   least-privilege IAM, Bedrock invoke permissions.
5. **ccloud provisioning** — finalize [`scripts/bootstrap_cockroach.sh`](../scripts/bootstrap_cockroach.sh).
6. **Concurrency demo** — multi-process action-lease race + crash-and-resume script for the video.
7. **Signed incident packages** — export closed-incident provenance bundles to S3.
8. **Demo video** (< 3 min) + hosted demo URL.

## Stretch
- MCP-server-driven read-only "explain this incident" tool.
- Grafana/console view of the belief-revision timeline.
- Belief calibration metrics (were high-confidence beliefs correct?).
