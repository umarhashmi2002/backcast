-- Give working-memory turns a deterministic order.
--
-- Turns were ordered by (created_at, id). A batched write inserts several rows in
-- one statement, so they share an identical `DEFAULT now()` timestamp and the
-- tiebreaker was a random UUID — meaning the reconstructed conversation could come
-- back out of order. For a scratchpad whose whole purpose is showing what the agent
-- was reasoning about, order is part of the data.
--
-- turn_seq is assigned per session by the writer and is what `ORDER BY` uses.

ALTER TABLE working_memory ADD COLUMN IF NOT EXISTS turn_seq INT8 NOT NULL DEFAULT 0;

DROP INDEX IF EXISTS working_session_idx;
CREATE INDEX IF NOT EXISTS working_session_seq_idx ON working_memory (session_id, turn_seq);

COMMENT ON COLUMN working_memory.turn_seq IS
    'Monotonic per-session turn number. Ordering key: created_at ties within a batched insert.';
