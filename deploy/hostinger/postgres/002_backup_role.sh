#!/bin/sh
set -eu

if [ -z "${CATALOG_BACKUP_PASSWORD:-}" ]; then
  echo "CATALOG_BACKUP_PASSWORD is required" >&2
  exit 1
fi

# Read across tenant RLS policies for complete dumps without superuser, write,
# role-management, or server-program privileges. Keep the password out of argv.
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
GRANT pg_read_all_data TO agent_economy_backup;
SQL
