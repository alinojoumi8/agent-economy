-- Hosted external-agent ownership, credentials, bindings, and immutable audit.

ALTER TABLE memberships DROP CONSTRAINT IF EXISTS memberships_role_check;
ALTER TABLE memberships ADD CONSTRAINT memberships_role_check
    CHECK (role IN ('observer', 'agent_owner', 'admin'));
ALTER TABLE invitations DROP CONSTRAINT IF EXISTS invitations_role_check;
ALTER TABLE invitations ADD CONSTRAINT invitations_role_check
    CHECK (role IN ('observer', 'agent_owner', 'admin'));

ALTER TABLE tenants ADD COLUMN max_external_agents_per_run integer NOT NULL DEFAULT 100
    CHECK (max_external_agents_per_run BETWEEN 0 AND 10000);

-- Public OAuth client metadata is intentionally not tenant-scoped. It carries
-- no credential or owner data and exists before the user chooses a connection.
CREATE TABLE external_oauth_clients (
    client_id text PRIMARY KEY CHECK (length(client_id) BETWEEN 16 AND 200),
    client_name text NOT NULL CHECK (length(client_name) BETWEEN 1 AND 200),
    redirect_uris text[] NOT NULL CHECK (cardinality(redirect_uris) BETWEEN 1 AND 10),
    grant_types text[] NOT NULL,
    response_types text[] NOT NULL,
    token_endpoint_auth_method text NOT NULL CHECK (token_endpoint_auth_method='none'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    CHECK (grant_types <@ ARRAY['authorization_code','refresh_token']::text[]),
    CHECK ('authorization_code'=ANY(grant_types)),
    CHECK (response_types=ARRAY['code']::text[])
);

CREATE TABLE external_agents (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    owner_user_id uuid NOT NULL,
    run_id uuid NOT NULL,
    run_connection_id uuid NOT NULL,
    display_name text NOT NULL CHECK (length(display_name) BETWEEN 1 AND 80),
    biography text NOT NULL DEFAULT '' CHECK (length(biography) <= 500),
    preferred_occupation text NOT NULL DEFAULT '' CHECK (length(preferred_occupation) <= 80),
    tier text NOT NULL CHECK (tier IN ('observer','commons','actor')),
    scopes text[] NOT NULL CHECK (cardinality(scopes) BETWEEN 0 AND 5),
    status text NOT NULL DEFAULT 'pending_actor'
        CHECK (status IN ('pending_actor','active','suspended','revoked')),
    actor_id bigint,
    last_seen_at timestamptz,
    lease_expires_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, owner_user_id) REFERENCES memberships(tenant_id, user_id),
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id) ON DELETE CASCADE,
    UNIQUE (tenant_id, id),
    UNIQUE (tenant_id, run_connection_id),
    UNIQUE (tenant_id, run_id, actor_id),
    CHECK (scopes <@ ARRAY['world.read','world.act','commons.read','commons.write','moderation.act']::text[]),
    CHECK ((tier='observer' AND actor_id IS NULL) OR tier<>'observer')
);

CREATE INDEX external_agents_owner_idx
    ON external_agents (tenant_id, owner_user_id, created_at, id);
CREATE INDEX external_agents_run_idx
    ON external_agents (tenant_id, run_id, status, id);

CREATE TABLE external_agent_credentials (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_agent_id uuid NOT NULL,
    kind text NOT NULL CHECK (kind IN ('personal','access','refresh')),
    token_hash character(64) NOT NULL UNIQUE CHECK (token_hash ~ '^[0-9a-f]{64}$'),
    scopes text[] NOT NULL CHECK (cardinality(scopes) BETWEEN 0 AND 5),
    audience text NOT NULL CHECK (length(audience) BETWEEN 1 AND 200),
    expires_at timestamptz NOT NULL,
    rotated_from_id uuid REFERENCES external_agent_credentials(id),
    revoked_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    last_used_at timestamptz,
    FOREIGN KEY (tenant_id, external_agent_id)
        REFERENCES external_agents(tenant_id, id) ON DELETE CASCADE,
    UNIQUE (tenant_id, id),
    CHECK (scopes <@ ARRAY['world.read','world.act','commons.read','commons.write','moderation.act']::text[]),
    CHECK (expires_at > created_at),
    CHECK (rotated_from_id IS NULL OR rotated_from_id <> id)
);

CREATE INDEX external_credentials_agent_idx
    ON external_agent_credentials (tenant_id, external_agent_id, kind, expires_at)
    WHERE revoked_at IS NULL;

CREATE TABLE external_actor_bindings (
    id uuid PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_agent_id uuid NOT NULL,
    run_id uuid NOT NULL,
    world_actor_id bigint,
    schedule_event_id bigint,
    status text NOT NULL CHECK (status IN ('scheduled','active','safe_policy','ended')),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    updated_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, external_agent_id)
        REFERENCES external_agents(tenant_id, id) ON DELETE CASCADE,
    FOREIGN KEY (tenant_id, run_id) REFERENCES runs(tenant_id, id) ON DELETE CASCADE,
    UNIQUE (tenant_id, external_agent_id, run_id),
    UNIQUE (tenant_id, run_id, world_actor_id)
);

CREATE TABLE external_security_audit_events (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    tenant_id uuid NOT NULL REFERENCES tenants(id) ON DELETE CASCADE,
    external_agent_id uuid,
    actor_user_id uuid,
    event_kind text NOT NULL CHECK (length(event_kind) BETWEEN 1 AND 100),
    outcome text NOT NULL CHECK (outcome IN ('allowed','denied','changed')),
    details_json jsonb NOT NULL DEFAULT '{}'::jsonb CHECK (jsonb_typeof(details_json)='object'),
    created_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    FOREIGN KEY (tenant_id, external_agent_id)
        REFERENCES external_agents(tenant_id, id),
    FOREIGN KEY (tenant_id, actor_user_id) REFERENCES memberships(tenant_id, user_id)
);

CREATE INDEX external_security_audit_time_idx
    ON external_security_audit_events (tenant_id, created_at DESC, id DESC);

CREATE TRIGGER external_security_audit_events_immutable_update
BEFORE UPDATE ON external_security_audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
CREATE TRIGGER external_security_audit_events_immutable_delete
BEFORE DELETE ON external_security_audit_events
FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();

ALTER TABLE external_agents ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_agents FORCE ROW LEVEL SECURITY;
CREATE POLICY external_agents_isolation ON external_agents
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE external_agent_credentials ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_agent_credentials FORCE ROW LEVEL SECURITY;
CREATE POLICY external_agent_credentials_isolation ON external_agent_credentials
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE external_actor_bindings ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_actor_bindings FORCE ROW LEVEL SECURITY;
CREATE POLICY external_actor_bindings_isolation ON external_actor_bindings
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

ALTER TABLE external_security_audit_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE external_security_audit_events FORCE ROW LEVEL SECURITY;
CREATE POLICY external_security_audit_events_isolation ON external_security_audit_events
    USING (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid)
    WITH CHECK (tenant_id = NULLIF(current_setting('app.tenant_id', true), '')::uuid);

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
      AND m.role IN ('observer', 'agent_owner', 'admin')
      AND u.disabled_at IS NULL
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION hosted_active_external_credential_tenant(p_token_hash text)
RETURNS uuid
LANGUAGE sql
VOLATILE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT c.tenant_id
    FROM public.external_agent_credentials AS c
    JOIN public.external_agents AS a
      ON a.tenant_id=c.tenant_id AND a.id=c.external_agent_id
    JOIN public.tenants AS t ON t.id=c.tenant_id
    WHERE c.token_hash=p_token_hash
      AND c.revoked_at IS NULL
      AND c.expires_at > clock_timestamp()
      AND a.status IN ('pending_actor','active')
      AND t.status='active'
    LIMIT 1
$$;

CREATE OR REPLACE FUNCTION hosted_external_agent_tenant(p_external_agent_id uuid)
RETURNS uuid
LANGUAGE sql
STABLE
SECURITY DEFINER
SET search_path = pg_catalog, public
AS $$
    SELECT a.tenant_id
    FROM public.external_agents AS a
    JOIN public.tenants AS t ON t.id=a.tenant_id
    WHERE a.id=p_external_agent_id AND a.status<>'revoked' AND t.status='active'
    LIMIT 1
$$;

REVOKE ALL ON FUNCTION hosted_active_external_credential_tenant(text) FROM PUBLIC;
REVOKE ALL ON FUNCTION hosted_external_agent_tenant(uuid) FROM PUBLIC;
