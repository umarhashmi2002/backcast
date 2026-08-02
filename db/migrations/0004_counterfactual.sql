-- Counterfactual replay: fork a resolved incident from a chosen point in time and
-- simulate alternative remediations against a deterministic incident model, then
-- compare outcomes and compute decision regret.

ALTER TYPE ledger_event_type ADD VALUE IF NOT EXISTS 'branch_simulated';
ALTER TYPE ledger_event_type ADD VALUE IF NOT EXISTS 'lesson_promoted';

-- Which deterministic scenario (hidden true cause + remediation effects) governs
-- this incident's simulation. NULL = not eligible for counterfactual replay.
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS scenario STRING;

CREATE TABLE IF NOT EXISTS incident_branches (
    id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id        STRING NOT NULL,
    incident_id   UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    label         STRING NOT NULL,
    forked_at_hlc DECIMAL,
    remediations  STRING[] NOT NULL DEFAULT ARRAY[]::STRING[],
    is_actual     BOOL NOT NULL DEFAULT false,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS branches_incident_idx ON incident_branches (incident_id, created_at);

COMMENT ON TABLE incident_branches IS 'A fork of an incident from forked_at_hlc, applying an alternative remediation sequence.';

CREATE TABLE IF NOT EXISTS branch_outcomes (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    branch_id           UUID NOT NULL REFERENCES incident_branches (id) ON DELETE CASCADE,
    recovered           BOOL NOT NULL,
    recurred            BOOL NOT NULL,
    time_to_recovery_s  FLOAT8 NOT NULL,
    unnecessary_actions INT8 NOT NULL,
    risk                FLOAT8 NOT NULL,
    cost                FLOAT8 NOT NULL,
    score               FLOAT8 NOT NULL,
    detail              JSONB NOT NULL DEFAULT '{}'::JSONB,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outcomes_branch_idx ON branch_outcomes (branch_id);

COMMENT ON TABLE branch_outcomes IS 'Deterministically computed outcome of a branch (never LLM-invented).';

CREATE TABLE IF NOT EXISTS simulation_runs (
    id               UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id           STRING NOT NULL,
    incident_id      UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    forked_at_hlc    DECIMAL,
    scenario         STRING,
    actual_branch_id UUID,
    best_branch_id   UUID,
    decision_regret  FLOAT8,
    summary          STRING,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS sim_runs_incident_idx ON simulation_runs (incident_id, created_at);

COMMENT ON TABLE simulation_runs IS 'A counterfactual comparison: actual vs best branch + decision regret.';
