# Hackathon submission disclosure

**Project:** Backcast — agentic memory for an SRE Incident Commander on CockroachDB + AWS.
**Entrant:** Umar Hashmi. **Event:** CockroachDB × AWS "Agentic Memory" Hackathon.

## New work statement
All code in this repository was created during the submission period. Standard tooling was used
(uv, ruff, mypy, pytest, AWS CDK, boto3, psycopg, pydantic, structlog, tenacity) and AI coding
assistants, as permitted. No pre-existing proprietary code was incorporated. The `cockroachdb-skills`
repo (Apache-2.0) is used as a development aid, not vendored into the product.

## Required: CockroachDB tools (≥ 2 — Backcast uses all four)
| Tool | Where |
|------|-------|
| Distributed Vector Indexing (C-SPANN) | `db/migrations/0001_init.sql` (vector indexes); `src/backcast/memory/evidence.py` (`<->` recall). |
| Managed MCP Server | Read-only agent introspection; see [`SECURITY.md`](./SECURITY.md) and [`DEPLOYMENT.md`](./DEPLOYMENT.md). |
| ccloud CLI | `scripts/bootstrap_cockroach.sh` (cluster + SA + DB provisioning, `-o json`). |
| Agent Skills Repo | Development-loop schema/perf/security review. |

## Required: AWS services (≥ 1 — Backcast uses several)
Amazon **Bedrock** (Claude reasoning + Titan Text Embeddings v2) · AWS **Lambda** (agent execution) ·
Amazon **S3** (raw artifacts + signed incident packages) · **API Gateway** · **EventBridge**
(consolidation schedule) · **Secrets Manager** (CockroachDB DSN) · **CloudWatch** (observability).
All infrastructure is defined as code with the **AWS CDK** (Python) under `infra/`.

## "CockroachDB as persistent memory, deployed on AWS"
CockroachDB is the single system of record for the agent's memory — evidence (episodic), beliefs and
provenance, semantic/procedural knowledge, action leases, and the audit ledger — not a cache alongside
another store. The agent runtime is AWS serverless.

## Deliverables
- ✅ Public repo (Apache-2.0), source, README, setup instructions.
- ✅ Reproducible demo: `make db-up && uv run backcast demo`.
- 🚧 Hosted demo URL + < 3-minute video (see [`ROADMAP.md`](./ROADMAP.md)).
- ✅ This services-used disclosure + [architecture diagram](./ARCHITECTURE.md).
