-- Tenant-local tamper-evident chaining for hosted control-plane audit records.
-- Existing rows remain explicitly unchained; no historical hash is fabricated.
ALTER TABLE audit_log
    ADD COLUMN tenant_sequence bigint,
    ADD COLUMN previous_entry_hash text,
    ADD COLUMN entry_hash text,
    ADD CONSTRAINT audit_log_chain_columns_consistent CHECK (
        (
            tenant_sequence IS NULL
            AND previous_entry_hash IS NULL
            AND entry_hash IS NULL
        )
        OR
        (
            tenant_sequence IS NOT NULL
            AND previous_entry_hash IS NOT NULL
            AND entry_hash IS NOT NULL
            AND tenant_sequence > 0
            AND previous_entry_hash ~ '^[0-9a-f]{64}$'
            AND entry_hash ~ '^[0-9a-f]{64}$'
        )
    );

CREATE UNIQUE INDEX audit_log_tenant_sequence_key
    ON audit_log (tenant_id, tenant_sequence)
    WHERE tenant_sequence IS NOT NULL;

CREATE INDEX audit_log_tenant_chain_head_idx
    ON audit_log (tenant_id, tenant_sequence DESC)
    INCLUDE (entry_hash)
    WHERE tenant_sequence IS NOT NULL;

CREATE OR REPLACE FUNCTION require_chained_audit_insert()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    IF NEW.tenant_sequence IS NULL
       OR NEW.previous_entry_hash IS NULL
       OR NEW.entry_hash IS NULL THEN
        RAISE EXCEPTION 'new audit_log rows require tenant hash-chain fields'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$;

CREATE TRIGGER audit_log_require_chain
BEFORE INSERT ON audit_log
FOR EACH ROW EXECUTE FUNCTION require_chained_audit_insert();

COMMENT ON COLUMN audit_log.entry_hash IS
    'Detects tenant-chain modification; not externally anchored non-repudiation.';
