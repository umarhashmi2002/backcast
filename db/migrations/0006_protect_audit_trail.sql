-- Stop one DELETE from erasing the "immutable" audit trail.
--
-- event_ledger, ledger_checkpoints and evidence all referenced incidents with
-- ON DELETE CASCADE, so `DELETE FROM incidents WHERE ...` silently took the
-- hash-chained ledger, its KMS-signed checkpoints, and the immutable evidence
-- with it. That contradicts the durability claim: the ledger is supposed to
-- outlive the GC window and be tamper-*evident*, which is meaningless if the
-- rows can be dropped as a side effect of deleting the parent row.
--
-- These three now RESTRICT instead, so an incident with recorded history cannot
-- be deleted at all. Retention is a deliberate, audited operation (export the
-- signed checkpoint, then remove ledger rows explicitly) rather than an implicit
-- cascade. Derived, reproducible tables (branches, outcomes, simulation runs,
-- beliefs, hypotheses, working memory) keep CASCADE: they are recomputable and
-- are not part of the audit record.
--
-- Idempotent: each constraint is dropped by name only if present, then re-added.

-- evidence.incident_id -------------------------------------------------------
ALTER TABLE evidence DROP CONSTRAINT IF EXISTS evidence_incident_id_fkey;
ALTER TABLE evidence ADD CONSTRAINT evidence_incident_id_fkey
    FOREIGN KEY (incident_id) REFERENCES incidents (id) ON DELETE RESTRICT;

-- event_ledger.incident_id ---------------------------------------------------
ALTER TABLE event_ledger DROP CONSTRAINT IF EXISTS event_ledger_incident_id_fkey;
ALTER TABLE event_ledger ADD CONSTRAINT event_ledger_incident_id_fkey
    FOREIGN KEY (incident_id) REFERENCES incidents (id) ON DELETE RESTRICT;

-- ledger_checkpoints.incident_id ---------------------------------------------
ALTER TABLE ledger_checkpoints DROP CONSTRAINT IF EXISTS ledger_checkpoints_incident_id_fkey;
ALTER TABLE ledger_checkpoints ADD CONSTRAINT ledger_checkpoints_incident_id_fkey
    FOREIGN KEY (incident_id) REFERENCES incidents (id) ON DELETE RESTRICT;

COMMENT ON TABLE event_ledger IS
    'Append-only hash-chained provenance. RESTRICT on incidents: deleting an incident with ledger history is refused, so the audit trail cannot be removed as a cascade side effect.';
