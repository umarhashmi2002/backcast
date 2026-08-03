-- Externally-signed checkpoints of the event ledger.
--
-- Each checkpoint signs the ledger's current root hash (the latest entry_hash) with
-- an external key (AWS KMS in the cloud, HMAC offline). Combined with the in-database
-- hash chain, this makes the audit trail tamper-evident even against someone who
-- could rewrite the chain — they would also have to forge the signature.
CREATE TABLE IF NOT EXISTS ledger_checkpoints (
    id          UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    org_id      STRING NOT NULL,
    incident_id UUID NOT NULL REFERENCES incidents (id) ON DELETE CASCADE,
    seq_covered INT8 NOT NULL,
    root_hash   STRING NOT NULL,
    signature   STRING NOT NULL,
    key_id      STRING NOT NULL,
    algorithm   STRING NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS checkpoints_incident_idx ON ledger_checkpoints (incident_id, seq_covered DESC);

COMMENT ON TABLE ledger_checkpoints IS 'Externally-signed root-hash checkpoints of the event ledger.';
