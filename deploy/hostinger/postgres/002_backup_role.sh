#!/bin/sh
set -eu

if [ -z "${CATALOG_BACKUP_PASSWORD:-}" ]; then
  echo "CATALOG_BACKUP_PASSWORD is required" >&2
  exit 1
fi

# Read the application's public schema across tenant RLS policies. Avoid
# pg_read_all_data: it also exposes protected system catalogs such as pg_authid.
# Keep the password out of argv.
psql --set=ON_ERROR_STOP=1 \
  --username "${POSTGRES_USER:-postgres}" \
  --dbname "$POSTGRES_DB" <<'SQL'
\getenv backup_password CATALOG_BACKUP_PASSWORD
SELECT format(
  'CREATE ROLE agent_economy_backup LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT BYPASSRLS CONNECTION LIMIT 2',
  :'backup_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_economy_backup')
\gexec

ALTER ROLE agent_economy_backup
  NOSUPERUSER NOCREATEDB NOCREATEROLE INHERIT BYPASSRLS CONNECTION LIMIT 2;
REVOKE pg_read_all_data FROM agent_economy_backup;
GRANT USAGE ON SCHEMA public TO agent_economy_backup;
GRANT SELECT ON ALL TABLES IN SCHEMA public TO agent_economy_backup;
GRANT SELECT ON ALL SEQUENCES IN SCHEMA public TO agent_economy_backup;
-- The migration administrator owns future application tables. These grants
-- apply when migrations run after fresh-volume initialization as well.
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON TABLES TO agent_economy_backup;
ALTER DEFAULT PRIVILEGES IN SCHEMA public
  GRANT SELECT ON SEQUENCES TO agent_economy_backup;
SQL
