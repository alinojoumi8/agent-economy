CREATE TABLE IF NOT EXISTS schema_migrations (
    version integer PRIMARY KEY CHECK (version > 0),
    name text NOT NULL UNIQUE,
    checksum_sha256 character(64) NOT NULL CHECK (checksum_sha256 ~ '^[0-9a-f]{64}$'),
    applied_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE tenants (
    id uuid PRIMARY KEY,
    slug text NOT NULL UNIQUE CHECK (slug = lower(slug) AND slug ~ '^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$'),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'suspended')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE users (
    id uuid PRIMARY KEY,
    email_normalized text NOT NULL UNIQUE CHECK (email_normalized = lower(email_normalized)),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 200),
    password_hash text NOT NULL,
    disabled_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE memberships (
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    role text NOT NULL CHECK (role IN ('observer', 'admin')),
    status text NOT NULL DEFAULT 'active' CHECK (status IN ('active', 'revoked')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    PRIMARY KEY (tenant_id, user_id)
);

CREATE TABLE sessions (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL,
    user_id uuid NOT NULL,
    token_hash character(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    csrf_secret_hash character(64) NOT NULL CHECK (csrf_secret_hash ~ '^[0-9a-f]{64}$'),
    expires_at timestamptz NOT NULL,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_seen_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, user_id) REFERENCES memberships(tenant_id, user_id) ON DELETE CASCADE,
    CHECK (expires_at > created_at)
);

CREATE INDEX sessions_tenant_user_idx ON sessions (tenant_id, user_id);
CREATE INDEX sessions_expiry_idx ON sessions (expires_at) WHERE revoked_at IS NULL;

CREATE TABLE invitations (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    email_normalized text NOT NULL CHECK (email_normalized = lower(email_normalized)),
    role text NOT NULL CHECK (role IN ('observer', 'admin')),
    token_hash character(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    invited_by_user_id uuid NOT NULL,
    expires_at timestamptz NOT NULL,
    accepted_at timestamptz,
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, invited_by_user_id) REFERENCES memberships(tenant_id, user_id),
    CHECK (expires_at > created_at),
    CHECK (accepted_at IS NULL OR revoked_at IS NULL)
);

CREATE INDEX invitations_tenant_email_idx ON invitations (tenant_id, email_normalized);
CREATE UNIQUE INDEX invitations_one_pending_per_email_idx
    ON invitations (tenant_id, email_normalized)
    WHERE accepted_at IS NULL AND revoked_at IS NULL;

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    owner_user_id uuid NOT NULL,
    run_key text NOT NULL CHECK (length(run_key) BETWEEN 1 AND 160),
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 240),
    status text NOT NULL DEFAULT 'created'
        CHECK (status IN ('created', 'starting', 'running', 'paused', 'snapshot_failed', 'stopped', 'failed', 'archived')),
    schema_version integer NOT NULL CHECK (schema_version > 0),
    engine_semantics_version integer NOT NULL CHECK (engine_semantics_version > 0),
    catalog_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(catalog_json) = 'object'),
    snapshot_object_key text,
    snapshot_sha256 character(64) CHECK (snapshot_sha256 ~ '^[0-9a-f]{64}$'),
    snapshot_size_bytes bigint CHECK (snapshot_size_bytes >= 0),
    snapshot_updated_at timestamptz,
    writer_lease_owner text,
    writer_lease_token uuid,
    writer_lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    UNIQUE (tenant_id, run_key),
    FOREIGN KEY (tenant_id, owner_user_id) REFERENCES memberships(tenant_id, user_id),
    CHECK (
        (snapshot_object_key IS NULL AND snapshot_sha256 IS NULL AND snapshot_size_bytes IS NULL AND snapshot_updated_at IS NULL)
        OR
        (snapshot_object_key IS NOT NULL AND snapshot_sha256 IS NOT NULL AND snapshot_size_bytes IS NOT NULL AND snapshot_updated_at IS NOT NULL)
    ),
    CHECK (
        (writer_lease_owner IS NULL AND writer_lease_token IS NULL AND writer_lease_expires_at IS NULL)
        OR
        (writer_lease_owner IS NOT NULL AND writer_lease_token IS NOT NULL AND writer_lease_expires_at IS NOT NULL)
    )
);

CREATE INDEX runs_tenant_updated_idx ON runs (tenant_id, updated_at DESC);
CREATE INDEX runs_active_lease_idx ON runs (writer_lease_expires_at) WHERE writer_lease_token IS NOT NULL;

CREATE TABLE audit_log (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE RESTRICT,
    actor_user_id uuid,
    action text NOT NULL CHECK (length(action) BETWEEN 1 AND 160),
    target_type text NOT NULL CHECK (length(target_type) BETWEEN 1 AND 80),
    target_id text,
    request_id text,
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details_json) = 'object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, actor_user_id) REFERENCES memberships(tenant_id, user_id)
);

CREATE INDEX audit_log_tenant_time_idx ON audit_log (tenant_id, created_at DESC, id DESC);

CREATE TABLE auth_attempts (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    user_id uuid,
    email_hash character(64) NOT NULL CHECK (email_hash ~ '^[0-9a-f]{64}$'),
    outcome text NOT NULL CHECK (outcome IN (
        'success', 'bad_credentials', 'rate_limited', 'locked', 'expired', 'revoked', 'csrf_failed'
    )),
    remote_address_hash character(64) CHECK (remote_address_hash ~ '^[0-9a-f]{64}$'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, user_id) REFERENCES memberships(tenant_id, user_id)
);

CREATE INDEX auth_attempts_tenant_time_idx ON auth_attempts (tenant_id, created_at DESC);
CREATE INDEX auth_attempts_email_window_idx ON auth_attempts (tenant_id, email_hash, created_at DESC);

CREATE OR REPLACE FUNCTION reject_audit_log_mutation()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only' USING ERRCODE = '55000';
END;
$$;

CREATE TRIGGER audit_log_no_update
BEFORE UPDATE ON audit_log
FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

CREATE TRIGGER audit_log_no_delete
BEFORE DELETE ON audit_log
FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

ALTER TABLE tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE tenants FORCE ROW LEVEL SECURITY;
CREATE POLICY tenants_isolation ON tenants
    USING (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE memberships ENABLE ROW LEVEL SECURITY;
ALTER TABLE memberships FORCE ROW LEVEL SECURITY;
CREATE POLICY memberships_isolation ON memberships
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE sessions ENABLE ROW LEVEL SECURITY;
ALTER TABLE sessions FORCE ROW LEVEL SECURITY;
CREATE POLICY sessions_isolation ON sessions
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE invitations ENABLE ROW LEVEL SECURITY;
ALTER TABLE invitations FORCE ROW LEVEL SECURITY;
CREATE POLICY invitations_isolation ON invitations
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE runs ENABLE ROW LEVEL SECURITY;
ALTER TABLE runs FORCE ROW LEVEL SECURITY;
CREATE POLICY runs_isolation ON runs
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE audit_log ENABLE ROW LEVEL SECURITY;
ALTER TABLE audit_log FORCE ROW LEVEL SECURITY;
CREATE POLICY audit_log_select ON audit_log
    FOR SELECT USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);
CREATE POLICY audit_log_insert ON audit_log
    FOR INSERT WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE auth_attempts ENABLE ROW LEVEL SECURITY;
ALTER TABLE auth_attempts FORCE ROW LEVEL SECURITY;
CREATE POLICY auth_attempts_isolation ON auth_attempts
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

-- Authentication begins before an RLS tenant can be selected. These narrowly
-- scoped SECURITY DEFINER functions reveal only the tenant UUID for an exact,
-- unguessable credential hash; all record reads still happen in a subsequent
-- tenant-scoped transaction. The migrator/database owner must own the functions.
CREATE OR REPLACE FUNCTION hosted_active_session_tenant(p_token_hash text)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT s.tenant_id
    FROM public.sessions AS s
    JOIN public.tenants AS t ON t.id = s.tenant_id
    JOIN public.memberships AS m
      ON m.tenant_id = s.tenant_id AND m.user_id = s.user_id
    JOIN public.users AS u ON u.id = s.user_id
    WHERE s.token_hash = p_token_hash
      AND s.revoked_at IS NULL
      AND s.expires_at > clock_timestamp()
      AND t.status = 'active'
      AND m.status = 'active'
      AND m.role IN ('observer', 'admin')
      AND u.disabled_at IS NULL
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION hosted_active_invitation_tenant(p_token_hash text)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT i.tenant_id
    FROM public.invitations AS i
    JOIN public.tenants AS t ON t.id = i.tenant_id
    JOIN public.memberships AS inviter
      ON inviter.tenant_id = i.tenant_id
     AND inviter.user_id = i.invited_by_user_id
    JOIN public.users AS inviter_user ON inviter_user.id = i.invited_by_user_id
    WHERE i.token_hash = p_token_hash
      AND i.accepted_at IS NULL
      AND i.revoked_at IS NULL
      AND i.expires_at > clock_timestamp()
      AND t.status = 'active'
      AND inviter.status = 'active'
      AND inviter.role = 'admin'
      AND inviter_user.disabled_at IS NULL
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION hosted_active_run_scopes()
RETURNS TABLE (tenant_id uuid, run_id uuid)
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT r.tenant_id, r.id
    FROM public.runs AS r
    JOIN public.tenants AS t ON t.id = r.tenant_id
    WHERE r.status IN ('starting', 'running', 'paused', 'snapshot_failed')
      AND t.status = 'active'
    ORDER BY r.tenant_id, r.id
$$;

CREATE OR REPLACE FUNCTION hosted_transfer_run_owner(
    p_tenant_id uuid,
    p_run_id uuid,
    p_new_owner_user_id uuid
)
RETURNS SETOF public.runs
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    UPDATE public.runs AS r
    SET owner_user_id = p_new_owner_user_id,
        updated_at = clock_timestamp()
    WHERE r.tenant_id = p_tenant_id
      AND r.id = p_run_id
      AND p_tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid
      AND EXISTS (
          SELECT 1
          FROM public.tenants AS t
          JOIN public.memberships AS m ON m.tenant_id = t.id
          WHERE t.id = p_tenant_id
            AND t.status = 'active'
            AND m.user_id = p_new_owner_user_id
            AND m.status = 'active'
            AND m.role IN ('observer', 'admin')
      )
    RETURNING r.*
$$;

REVOKE ALL ON FUNCTION hosted_active_session_tenant(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION hosted_active_invitation_tenant(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION hosted_active_run_scopes() FROM PUBLIC;
REVOKE ALL ON FUNCTION hosted_transfer_run_owner(uuid, uuid, uuid) FROM PUBLIC;
