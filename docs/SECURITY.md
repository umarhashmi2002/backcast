# Security & product-readiness

Backcast is designed so an *autonomous* agent can be trusted to act. That requires more than a working
happy path — it requires safe defaults, least privilege, and provable behavior when things go wrong.

## Access control
- **Tenant-scoped data model** (not enforced isolation). Every row is scoped by `org_id`, which is also
  the **prefix column** of each C-SPANN vector index, so similarity search is pre-filtered per tenant.
  This is efficient tenant scoping, not a hard isolation guarantee — a missing app filter could still
  cross tenants. Production would add CockroachDB **row-level security** (`USING` / `WITH CHECK` on
  `org_id`) and per-service DB roles rather than one shared DSN.
- **Typed, parameterized SQL** — the application never string-concatenates SQL. The **Managed MCP
  Server** was used during development for read-only DB inspection; it is **not** on the runtime agent
  path (a read-only MCP "explain this incident" auditor is on the roadmap).
- **ccloud service accounts.** Provisioning uses a scoped service account (Cluster Creator/Admin),
  with credentials kept out of the repo (`.gitignore` excludes `service-account*.json`, `cc_*`).
- **AWS IAM least privilege.** Each Lambda gets only the actions it needs (specific Bedrock model ARNs,
  one S3 prefix, one Secrets Manager secret). No wildcard admin roles.
- **Secrets.** The CockroachDB DSN lives in AWS Secrets Manager, injected at runtime — never in code,
  env files, or logs.

## Safe autonomous action
- **Single-owner claim.** `UNIQUE(org_id, action_key)` guarantees exactly one *current logical owner*
  of an action, even under a thundering herd of duplicate alerts.
- **Fencing tokens.** Every takeover bumps `lease_generation`; writes/completions are gated on
  `holder = me AND lease_generation = mine AND not expired`. An expired lease proves the holder failed
  to renew — *not* that it is dead — so a revived stale worker is **fenced out** and cannot finalize.
- **Idempotency.** Each claim records a `UNIQUE(idempotency_key)`, which is what an executor would
  present to make its effect *safely repeatable*. Because a DB transaction cannot atomically commit
  with an external AWS side effect, Backcast does **not** claim "exactly-once execution" — it
  guarantees one canonical action intent with safe repetition. Note that **this build never executes
  the action**: the lease is claimed and held, so no external state is read or written.
- **SQL-safe reconstruction.** `AS OF SYSTEM TIME` requires a constant; the HLC is validated against a
  strict decimal regex and ids are validated before inlining.

## Auditability
- **Immutable evidence** and an append-only, **hash-chained** `event_ledger` (`entry_hash =
  sha256(prev_hash || seq || event_type || payload || actor)`) make the trail **tamper-evident within
  the database** — any edit that doesn't also rewrite every later hash is detectable (`EventLedger.verify()`).
- **Durable integrity.** For tamper-evidence beyond a database administrator, periodic root-hash
  checkpoints are signed with **AWS KMS** (ECDSA P-256) and stored in `ledger_checkpoints`. The
  signature proves the root hash was authenticated by the KMS key (not an independent timestamp —
  CloudTrail + the S3 object give timing/persistence). **Optional S3 Object Lock export is not enabled
  in the current demo.**
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
