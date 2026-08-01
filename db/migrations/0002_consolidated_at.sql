-- Track which resolved incidents the scheduled consolidator has already processed,
-- so the reflection loop is idempotent and does not re-distill the same incident.
ALTER TABLE incidents ADD COLUMN IF NOT EXISTS consolidated_at TIMESTAMPTZ;

CREATE INDEX IF NOT EXISTS incidents_consolidation_idx ON incidents (status, consolidated_at)
    WHERE consolidated_at IS NULL;
