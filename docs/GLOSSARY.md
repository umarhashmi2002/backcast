# Glossary

Every domain and technical term Backcast uses, grouped. If a judge (or teammate) hits an unfamiliar
word anywhere in the repo, it's defined here.

## The problem domain

- **SRE (Site Reliability Engineering)** — the discipline of keeping production services reliable.
- **On-call** — the engineer responsible for responding to production alerts at a given time.
- **Incident** — a period of degraded/broken service that requires response. Modeled as the
  `incidents` state machine (`triggered → acknowledged → investigating → mitigating → resolved → closed`).
- **Incident Commander** — the person (here, the agent) coordinating an incident's diagnosis and
  remediation.
- **Remediation** — an action taken to fix or mitigate an incident (rollback, restart, scale, etc.).
- **Root cause** — the underlying reason for an incident (vs. a symptom).
- **Post-incident review / postmortem** — the after-the-fact analysis asking *"what did we know, and
  was that the right call?"* — the two questions Backcast is built to answer.
- **Alert fingerprint** — a stable id an alerting system assigns to a firing alert; Backcast uses it as
  `external_id` for **idempotent ingest** (the same alert never creates two incidents).

## Agentic memory

- **Agentic memory** — durable, queryable state an AI agent persists across sessions: what it observed,
  believed, decided, and learned. Backcast's thesis is that this belongs in one transactional,
  temporal database.
- **Episodic memory** — the raw, immutable record of what happened (`evidence` + `event_ledger`).
- **Semantic memory** — distilled, reusable facts learned from episodes (`semantic_memory`).
- **Procedural memory** — remediations that worked, weighted by outcome (`procedural_memory`).
- **Working memory** — the ephemeral, per-session scratchpad (`working_memory`), safe to delete.
- **Evidence** — an immutable observed signal (metric, log, trace, deploy, human note). Never updated
  or deleted.
- **Hypothesis** — a candidate explanation for an incident.
- **Belief** — a *time-versioned* confidence (0–1) in a hypothesis. Content is immutable; a new belief
  **supersedes** the old one (`valid_from`, `valid_until`, `superseded_by`).
- **Provenance graph** — typed edges recording *why* the agent concluded something: evidence
  `supports`/`contradicts` a hypothesis, an action `verifies` it, a belief `supersedes` another.
- **Consolidation / reflection** — the gated process that distills a *closed* incident's evidence into
  semantic/procedural memory (`Consolidator`). Evidence-preserving: it never rewrites raw evidence.
- **Retrieval decay** — lowering a memory's recall priority over time (`retrieval_score`) without
  deleting it, so stale knowledge fades but is never lost.

## CockroachDB / temporal

- **CockroachDB** — a distributed, PostgreSQL-compatible SQL database with MVCC and time-travel.
- **MVCC (Multi-Version Concurrency Control)** — the database keeps historical versions of each row,
  which is what makes time-travel and the no-leak guarantee possible.
- **HLC (Hybrid Logical Clock)** — CockroachDB's timestamp combining physical + logical time.
  `cluster_logical_timestamp()` returns the current HLC as a decimal; Backcast stores it as `db_ts`.
- **`AS OF SYSTEM TIME`** — a SQL clause that reads a transactionally-consistent snapshot of the whole
  database at a past HLC. The core of **temporal reconstruction**.
- **Temporal reconstruction** — rebuilding exactly what the agent knew/believed at a chosen instant.
- **No-leak guarantee** — evidence written *after* the reconstruction timestamp is invisible to the
  past view, enforced by MVCC (not application filtering).
- **GC window (garbage-collection window)** — how far back `AS OF SYSTEM TIME` can read before old
  versions are collected. Durable history beyond it lives in the ledger + signed S3 packages.
- **Bitemporal** — tracking two time axes: *system time* (when the DB committed a fact) and *valid
  time* (`valid_from`/`valid_until`, when a belief was held).
- **Row-Level TTL** — CockroachDB feature that physically expires rows after a duration; used only for
  disposable `working_memory`.

## Vectors / retrieval

- **Embedding** — a numeric vector representing text meaning; similar text → nearby vectors.
- **Titan Text Embeddings v2** — the Amazon Bedrock model producing 1024-dim, L2-normalized embeddings.
- **Vector index** — a database index that accelerates nearest-neighbor search over embeddings.
- **C-SPANN** — CockroachDB's distributed, disk-based **ANN** vector index (SPANN-based).
- **ANN (Approximate Nearest Neighbor)** — fast, approximate similarity search at scale.
- **Cosine / L2 distance** — two ways to measure vector closeness. For L2-normalized vectors they are
  **ranking-equivalent** (the ordering matches; the numeric distances differ).
- **Historical recall** — recall as of a past HLC; Backcast scores it by *exact* distance over a
  bounded set rather than assuming the ANN index accelerates a time-travel read.

## Actions / safety

- **Action lease** — a transactional claim (`action_leases`) giving exactly one worker the right to run
  a specific action (`UNIQUE(org_id, action_key)`).
- **Fencing token / `lease_generation`** — a counter bumped on every takeover; writes are gated on the
  current generation, so a revived stale worker is **fenced out** and cannot finalize.
- **Idempotency key** — a token that makes an external effect **safely repeatable** (applying it twice
  is a no-op).
- **Heartbeat** — a periodic liveness update that keeps a long-running lease from expiring.
- **Takeover** — a healthy worker claiming an *expired* lease (bumping the fencing generation).
- **"Exactly one owner, safe repetition"** — Backcast's precise guarantee. It does **not** claim
  "exactly-once external effects" (a DB transaction can't atomically commit an external AWS side effect).

## Audit

- **Event ledger** — an append-only, per-incident log (`event_ledger`) of every significant event.
- **Hash chain** — each ledger entry's `entry_hash = sha256(prev_hash ‖ seq ‖ event_type ‖ payload ‖
  actor)`, so any tampering that doesn't rewrite every later hash is detectable (**tamper-evident**).
- **KMS-signed checkpoint** — a periodically-signed ledger root hash stored in `ledger_checkpoints`
  (optionally exported to **S3 Object Lock** for WORM retention — not enabled in the demo), giving
  tamper-evidence beyond a database administrator's reach. The signature authenticates the root hash;
  timing/persistence come from CloudTrail + the S3 object, not the signature itself.

## Counterfactual replay

- **Counterfactual** — "what would have happened if we had decided differently."
- **Incident branch** — a fork of a resolved incident applying an alternative remediation sequence
  (`incident_branches`).
- **Deterministic incident model** — a scenario with a *hidden true cause* and remediations with
  *defined effects*; it computes each branch's outcome so the LLM never invents whether an action worked.
- **Scenario** — the named model attached to an incident (`db_pool_exhaustion`, `memory_leak`,
  `cert_expiry`).
- **Decision regret** — `best_branch.score − actual_branch.score`: how much better the optimal decision
  would have been.

## AWS / infrastructure

- **Amazon Bedrock** — AWS's managed foundation-model service. Backcast uses **Nova Pro** (reasoning +
  tool use via the **Converse API**) and **Titan** (embeddings).
- **Tool use / Converse API** — Bedrock's unified chat API where the model can call typed tools.
- **AWS Lambda** — serverless functions; Backcast ships each handler as a container image.
- **Function URL / API Gateway** — HTTPS entry points to Lambdas (API Gateway adds HMAC auth +
  throttling — hardening in progress).
- **Secrets Manager** — stores the CockroachDB DSN (+ CA cert); read at Lambda cold start.
- **EventBridge** — schedules the consolidation Lambda.
- **CloudWatch** — logs, metrics, alarms, dashboard.
- **S3** — object storage for raw alert artifacts + signed incident packages.
- **KMS (Key Management Service)** — signs ledger checkpoints.
- **AWS CDK** — infrastructure-as-code (Python) that provisions all of the above.

## CockroachDB tools (hackathon requirement)

- **Managed MCP Server** — a read-only-by-default, audited endpoint letting AI tools query the cluster
  (Model Context Protocol).
- **ccloud CLI** — the agent-friendly (`-o json`) CLI for provisioning CockroachDB Cloud clusters.
- **Agent Skills** — CockroachDB's open-source, machine-executable operational skills used in the dev loop.
