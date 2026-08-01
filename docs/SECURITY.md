# Security & product-readiness

Retrace is designed so an *autonomous* agent can be trusted to act. That requires more than a working
happy path — it requires safe defaults, least privilege, and provable behavior when things go wrong.

## Access control
- **Multi-tenant isolation.** Every row is scoped by `org_id`, which is also the **prefix column** of
  each C-SPANN vector index, so similarity search is pre-filtered per tenant.
- **CockroachDB MCP server: read-only by default.** The agent's exploratory/introspection access goes
  through the managed MCP endpoint in read-only mode with full audit logging; writes go through the
  application's typed, parameterized statements — never string-concatenated SQL.
- **ccloud service accounts.** Provisioning uses a scoped service account (Cluster Creator/Admin),
  with credentials kept out of the repo (`.gitignore` excludes `service-account*.json`, `cc_*`).
- **AWS IAM least privilege.** Each Lambda gets only the actions it needs (specific Bedrock model ARNs,
  one S3 prefix, one Secrets Manager secret). No wildcard admin roles.
- **Secrets.** The CockroachDB DSN lives in AWS Secrets Manager, injected at runtime — never in code,
  env files, or logs.

## Safe autonomous action
- **Single-owner action leases.** `UNIQUE(org_id, action_key)` guarantees exactly one worker may
  execute a given action, even under a thundering herd of duplicate alerts.
- **Idempotency.** A `UNIQUE(idempotency_key)` and transactional completion mean a retried or resumed
  worker never double-executes.
- **Crash recovery.** `lease_expires_at` + `take_over_if_expired` let a healthy worker resume a dead
  holder's action safely — and only after expiry, never while the holder is alive.
- **SQL-safe reconstruction.** `AS OF SYSTEM TIME` requires a constant; the HLC is validated against a
  strict decimal regex and the incident id is validated as a UUID before inlining.

## Auditability
- **Immutable evidence** and an **append-only, hash-chained `event_ledger`** (`entry_hash =
  sha256(prev_hash || seq || event_type || payload || actor)`) make the decision trail tamper-evident;
  `EventLedger.verify()` recomputes the chain.
- **Time-travel** answers "what did we know, and when" precisely inside the GC window; the ledger and
  S3 incident packages provide durable provenance beyond it.

## Resilience & observability
- Connection-liveness checks and `tenacity` retries on transient `OperationalError`; serialization
  retries on ledger contention.
- Structured JSON logging (structlog) to CloudWatch; the migration runner is idempotent.
- CI runs lint, `mypy --strict`, unit tests, and **integration tests against a live CockroachDB**.

## Known limitations
- Row-Level TTL applies only to `working_memory`; do not point it at evidence.
- Historical reads are bounded by the GC window — durable audit relies on the ledger + S3, by design.
- The offline `HashEmbedder` is for dev/CI only and is not semantically meaningful; production uses
  Bedrock Titan.
