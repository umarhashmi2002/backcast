-- =====================================================================
-- Backcast — initial schema
--
-- One temporal system of record for an SRE Incident Commander agent:
--   * operational incident state (strongly consistent),
--   * immutable evidence + hash-chained event ledger (permanent provenance),
--   * time-versioned beliefs + a typed provenance graph (belief revision),
--   * transactional action leases (safe autonomous action + idempotency),
--   * long-term semantic/procedural memory (C-SPANN vector recall),
--   * disposable working memory (Row-Level TTL).
--
-- Two temporal axes make "what did the agent believe at 03:14?" answerable:
--   1. system time  -> AS OF SYSTEM TIME <db_ts> (captured HLC per write),
--   2. valid time   -> beliefs.valid_from / valid_until (application ledger).
--
-- Embedding dimension = 1024 (Amazon Titan Text Embeddings v2). If you change
-- the embedding model, update every VECTOR(1024) accordingly.
-- =====================================================================

-- ---------------------------------------------------------------------
-- Enumerated domain types
-- ---------------------------------------------------------------------
CREATE TYPE IF NOT EXISTS incident_severity AS ENUM ('sev1', 'sev2', 'sev3', 'sev4', 'sev5');

CREATE TYPE IF NOT EXISTS incident_status AS ENUM (
    'triggered', 'acknowledged', 'investigating', 'mitigating', 'resolved', 'closed'
);

CREATE TYPE IF NOT EXISTS evidence_kind AS ENUM (
    'alert', 'metric', 'log', 'trace', 'deploy', 'topology', 'human', 'external'
);

CREATE TYPE IF NOT EXISTS hypothesis_status AS ENUM (
    'open', 'supported', 'refuted', 'confirmed', 'dismissed'
);

CREATE TYPE IF NOT EXISTS lease_status AS ENUM (
    'claimed', 'executing', 'completed', 'failed', 'released'
);

-- Polymorphic node/edge types for the provenance graph.
CREATE TYPE IF NOT EXISTS node_type AS ENUM (
    'evidence', 'hypothesis', 'belief', 'action', 'incident', 'procedure', 'semantic_fact'
);

CREATE TYPE IF NOT EXISTS edge_relation AS ENUM (
    'supports', 'contradicts', 'verifies', 'refutes', 'supersedes',
    'derived_from', 'recalled_for', 'remediates'
);

CREATE TYPE IF NOT EXISTS ledger_event_type AS ENUM (
    'incident_opened', 'evidence_recorded', 'hypothesis_formed', 'belief_updated',
    'action_claimed', 'action_executing', 'action_executed', 'action_failed',
    'incident_status_changed', 'incident_resolved', 'procedure_learned',
    'fact_learned', 'fact_superseded'
);

-- ---------------------------------------------------------------------
-- incidents — the operational state machine (strongly consistent)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS incidents (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          STRING NOT NULL,
    external_id     STRING,
    title           STRING NOT NULL,
    summary         STRING,
    service         STRING NOT NULL,
    severity        incident_severity NOT NULL DEFAULT 'sev3',
    status          incident_status NOT NULL DEFAULT 'triggered',
    state_version   INT8 NOT NULL DEFAULT 1,
    labels          JSONB NOT NULL DEFAULT '{}'::JSONB,
    resolution      STRING,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    acknowledged_at TIMESTAMPTZ,
    resolved_at     TIMESTAMPTZ,
    closed_at       TIMESTAMPTZ,
    UNIQUE (org_id, external_id)
);

CREATE INDEX IF NOT EXISTS incidents_org_status_idx ON incidents (org_id, status, created_at DESC);
CREATE INDEX IF NOT EXISTS incidents_org_service_idx ON incidents (org_id, service, created_at DESC);

COMMENT ON TABLE incidents IS 'Operational incident records; the transactional system of record.';
COMMENT ON COLUMN incidents.state_version IS 'Monotonic version bumped on each status change; referenced by beliefs.';
COMMENT ON COLUMN incidents.external_id IS 'Idempotency/dedup key from the alert source (e.g. Alertmanager fingerprint).';

-- ---------------------------------------------------------------------
-- evidence — IMMUTABLE, append-only raw experience (episodic memory)
-- Never updated or deleted; the ground truth the agent reasoned over.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS evidence (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      STRING NOT NULL,
    incident_id UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    kind        evidence_kind NOT NULL,
    source      STRING NOT NULL DEFAULT 'system',
    content     STRING NOT NULL,
    observed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    embedding   VECTOR(1024),
    s3_uri      STRING,
    db_ts       DECIMAL NOT NULL DEFAULT cluster_logical_timestamp(),
    metadata    JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- C-SPANN distributed vector index, prefixed by org_id for tenant isolation
-- and pre-filtering. Default (L2) op class + the `<->` operator; because Titan
-- v2 embeddings are L2-normalized, L2 distance ranks identically to cosine and
-- is portable across all CockroachDB 25.2+ clusters.
CREATE VECTOR INDEX evidence_embedding_idx ON evidence (org_id, embedding);
CREATE INDEX IF NOT EXISTS evidence_incident_idx ON evidence (incident_id, observed_at);

COMMENT ON TABLE evidence IS 'Immutable raw signals/observations; embedded for cross-incident semantic recall.';
COMMENT ON COLUMN evidence.observed_at IS 'When the signal became available (valid-time axis for no-leak reconstruction).';
COMMENT ON COLUMN evidence.db_ts IS 'HLC commit timestamp captured at insert (system-time axis for AS OF SYSTEM TIME).';

-- ---------------------------------------------------------------------
-- hypotheses — candidate explanations the agent forms during an incident
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS hypotheses (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      STRING NOT NULL,
    incident_id UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    statement   STRING NOT NULL,
    status      hypothesis_status NOT NULL DEFAULT 'open',
    db_ts       DECIMAL NOT NULL DEFAULT cluster_logical_timestamp(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS hypotheses_incident_idx ON hypotheses (incident_id, created_at);

-- ---------------------------------------------------------------------
-- beliefs — time-versioned confidence over hypotheses (append-only)
-- A confidence change closes the prior row (valid_until) and inserts a new
-- one; the full revision history is preserved for provenance.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS beliefs (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id                STRING NOT NULL,
    incident_id           UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    hypothesis_id         UUID NOT NULL REFERENCES hypotheses (id) ON DELETE CASCADE,
    confidence            FLOAT8 NOT NULL,
    rationale             STRING,
    valid_from            TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until           TIMESTAMPTZ,
    superseded_by         UUID REFERENCES beliefs (id),
    incident_state_version INT8,
    model_id              STRING,
    prompt_version        STRING,
    created_by            STRING NOT NULL DEFAULT 'agent',
    db_ts                 DECIMAL NOT NULL DEFAULT cluster_logical_timestamp(),
    created_at            TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS beliefs_incident_idx ON beliefs (incident_id, hypothesis_id, valid_from);
CREATE INDEX IF NOT EXISTS beliefs_current_idx ON beliefs (incident_id, hypothesis_id)
    WHERE valid_until IS NULL;

COMMENT ON TABLE beliefs IS 'Time-versioned belief states; the application-time ledger of what the agent thought.';
COMMENT ON COLUMN beliefs.valid_until IS 'NULL means currently held; set when a newer belief supersedes this one.';

-- ---------------------------------------------------------------------
-- provenance_edges — the typed belief graph (why the agent concluded X)
-- Polymorphic (type,id) endpoints; referential integrity enforced in app.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS provenance_edges (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      STRING NOT NULL,
    incident_id UUID REFERENCES incidents (id) ON DELETE CASCADE,
    src_type    node_type NOT NULL,
    src_id      UUID NOT NULL,
    relation    edge_relation NOT NULL,
    dst_type    node_type NOT NULL,
    dst_id      UUID NOT NULL,
    weight      FLOAT8 NOT NULL DEFAULT 1.0,
    note        STRING,
    db_ts       DECIMAL NOT NULL DEFAULT cluster_logical_timestamp(),
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS edges_incident_idx ON provenance_edges (incident_id, created_at);
CREATE INDEX IF NOT EXISTS edges_src_idx ON provenance_edges (src_type, src_id);
CREATE INDEX IF NOT EXISTS edges_dst_idx ON provenance_edges (dst_type, dst_id);

COMMENT ON TABLE provenance_edges IS 'Directed, typed edges: evidence supports/contradicts hypotheses, actions verify them, beliefs supersede beliefs.';

-- ---------------------------------------------------------------------
-- action_leases — transactional single-owner claims + idempotency
-- 25 duplicate workers race; the UNIQUE(org_id, action_key) constraint
-- lets exactly one win. idempotency_key prevents double execution across
-- crash/retry. lease_expires_at enables safe takeover of a dead holder.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS action_leases (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id          STRING NOT NULL,
    incident_id     UUID REFERENCES incidents (id) ON DELETE CASCADE,
    action_key      STRING NOT NULL,
    idempotency_key STRING NOT NULL,
    holder          STRING NOT NULL,
    status          lease_status NOT NULL DEFAULT 'claimed',
    lease_expires_at TIMESTAMPTZ NOT NULL,
    attempts        INT8 NOT NULL DEFAULT 1,
    payload         JSONB NOT NULL DEFAULT '{}'::JSONB,
    result          JSONB,
    error           STRING,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (org_id, action_key),
    UNIQUE (idempotency_key)
);

CREATE INDEX IF NOT EXISTS leases_incident_idx ON action_leases (incident_id, status);

COMMENT ON TABLE action_leases IS 'Memory-governed action ownership: one claim per action_key, idempotent execution, crash-safe takeover.';

-- ---------------------------------------------------------------------
-- event_ledger — IMMUTABLE, hash-chained permanent provenance
-- Survives the GC window (unlike AS OF SYSTEM TIME); tamper-evident via
-- a per-incident hash chain (entry_hash = H(prev_hash || seq || payload)).
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS event_ledger (
    id          UUID NOT NULL DEFAULT gen_random_uuid(),
    org_id      STRING NOT NULL,
    incident_id UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    seq         INT8 NOT NULL,
    event_type  ledger_event_type NOT NULL,
    payload     JSONB NOT NULL,
    actor       STRING,
    model_id    STRING,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    db_ts       DECIMAL NOT NULL DEFAULT cluster_logical_timestamp(),
    prev_hash   STRING,
    entry_hash  STRING NOT NULL,
    PRIMARY KEY (incident_id, seq)
);

CREATE INDEX IF NOT EXISTS ledger_org_time_idx ON event_ledger (org_id, occurred_at);

COMMENT ON TABLE event_ledger IS 'Append-only, hash-chained audit trail; durable provenance independent of the GC window.';

-- ---------------------------------------------------------------------
-- semantic_memory — distilled, revisable knowledge (retrieval-decayed)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS semantic_memory (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           STRING NOT NULL,
    statement        STRING NOT NULL,
    source           STRING NOT NULL DEFAULT 'consolidation',
    service          STRING,
    confidence       FLOAT8 NOT NULL DEFAULT 0.6,
    importance       FLOAT8 NOT NULL DEFAULT 0.5,
    retrieval_score  FLOAT8 NOT NULL DEFAULT 1.0,
    embedding        VECTOR(1024),
    access_count     INT8 NOT NULL DEFAULT 0,
    last_accessed_at TIMESTAMPTZ,
    valid_from       TIMESTAMPTZ NOT NULL DEFAULT now(),
    valid_until      TIMESTAMPTZ,
    superseded_by    UUID REFERENCES semantic_memory (id),
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE VECTOR INDEX semantic_embedding_idx ON semantic_memory (org_id, embedding);
CREATE INDEX IF NOT EXISTS semantic_org_service_idx ON semantic_memory (org_id, service);

COMMENT ON TABLE semantic_memory IS 'Consolidated knowledge distilled from evidence; revisable and retrieval-decayed, never silently deleted.';
COMMENT ON COLUMN semantic_memory.retrieval_score IS 'Decays over time to lower recall priority without destroying the fact.';

-- ---------------------------------------------------------------------
-- procedural_memory — remediations that worked (confidence-weighted)
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS procedural_memory (
    id                 UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id             STRING NOT NULL,
    name               STRING NOT NULL,
    trigger_pattern    STRING NOT NULL,
    steps              STRING NOT NULL,
    service            STRING,
    embedding          VECTOR(1024),
    success_count      INT8 NOT NULL DEFAULT 0,
    failure_count      INT8 NOT NULL DEFAULT 0,
    importance         FLOAT8 NOT NULL DEFAULT 0.5,
    retrieval_score    FLOAT8 NOT NULL DEFAULT 1.0,
    source_incident_id UUID REFERENCES incidents (id) ON DELETE SET NULL,
    last_used_at       TIMESTAMPTZ,
    created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE VECTOR INDEX procedural_embedding_idx ON procedural_memory (org_id, embedding);

COMMENT ON TABLE procedural_memory IS 'Learned remediation procedures, matched to new incidents by trigger similarity; confidence from success/failure counts.';
COMMENT ON COLUMN procedural_memory.embedding IS 'Embedding of trigger_pattern (the symptom), not of the steps.';

-- ---------------------------------------------------------------------
-- agent_sessions + working_memory — the live context window
-- working_memory is disposable and physically expired via Row-Level TTL.
-- ---------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS agent_sessions (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         STRING NOT NULL,
    incident_id    UUID REFERENCES incidents (id) ON DELETE CASCADE,
    worker_id      STRING,
    summary        STRING,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_active_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS working_memory (
    id             UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id         STRING NOT NULL,
    session_id     UUID NOT NULL REFERENCES agent_sessions (id) ON DELETE CASCADE,
    incident_id    UUID REFERENCES incidents (id) ON DELETE CASCADE,
    role           STRING NOT NULL,
    content        STRING NOT NULL,
    token_estimate INT8 NOT NULL DEFAULT 0,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
) WITH (ttl_expire_after = '24 hours', ttl_job_cron = '@hourly');

CREATE INDEX IF NOT EXISTS working_session_idx ON working_memory (session_id, created_at);

COMMENT ON TABLE working_memory IS 'Ephemeral per-session turns; the ONLY table with Row-Level TTL (safe to physically delete).';

-- ---------------------------------------------------------------------
-- Convenience view: the agent's current belief per hypothesis
-- ---------------------------------------------------------------------
CREATE VIEW IF NOT EXISTS current_beliefs AS
    SELECT b.org_id, b.incident_id, b.hypothesis_id, h.statement AS hypothesis,
           h.status AS hypothesis_status, b.confidence, b.rationale,
           b.valid_from, b.incident_state_version, b.model_id
    FROM beliefs b
    JOIN hypotheses h ON h.id = b.hypothesis_id
    WHERE b.valid_until IS NULL;
