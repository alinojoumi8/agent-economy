#!/bin/sh
set -eu

if [ -z "${APP_DATABASE_PASSWORD:-}" ]; then
  echo "APP_DATABASE_PASSWORD is required" >&2
  exit 1
fi
if [ -z "${SUPERVISOR_DATABASE_PASSWORD:-}" ]; then
  echo "SUPERVISOR_DATABASE_PASSWORD is required" >&2
  exit 1
fi

psql --set=ON_ERROR_STOP=1 \
  --username "$POSTGRES_USER" \
  --dbname "$POSTGRES_DB" \
  --set=app_password="$APP_DATABASE_PASSWORD" \
  --set=supervisor_password="$SUPERVISOR_DATABASE_PASSWORD" <<'SQL'
SELECT format(
  'CREATE ROLE agent_economy_app LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'app_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_economy_app')
\gexec

ALTER ROLE agent_economy_app
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;

SELECT format(
  'CREATE ROLE agent_economy_supervisor LOGIN PASSWORD %L NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS',
  :'supervisor_password'
)
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'agent_economy_supervisor')
\gexec

ALTER ROLE agent_economy_supervisor
  NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT NOBYPASSRLS;
SQL
