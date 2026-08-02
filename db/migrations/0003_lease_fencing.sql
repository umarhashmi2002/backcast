-- Fencing tokens for action leases.
--
-- A UNIQUE(org_id, action_key) claim prevents concurrent ownership, but an
-- expired lease does NOT prove the previous holder is dead (it may be paused,
-- delayed, or still mid external call). A monotonically increasing
-- `lease_generation`, bumped on every takeover, fences the stale holder out: its
-- writes/completions are rejected because they carry an older generation. A
-- `heartbeat_at` lets a live holder prove liveness during long external actions.
ALTER TABLE action_leases ADD COLUMN IF NOT EXISTS lease_generation INT8 NOT NULL DEFAULT 1;
ALTER TABLE action_leases ADD COLUMN IF NOT EXISTS heartbeat_at TIMESTAMPTZ NOT NULL DEFAULT now();
