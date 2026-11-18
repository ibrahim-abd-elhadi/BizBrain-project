#!/bin/sh
# brain-api's login inside brain_db (feature 003 research R-16, D-45; feature 004 R-04): it reads
# eight result tables and writes only the four proposal tables.
#
# Idempotent: runs by itself on a fresh volume (after 01-create-databases.sh), and can be run
# again at any time on an existing volume:
#   docker compose exec -T postgres sh /docker-entrypoint-initdb.d/02-brain-api-role.sh
# It creates or updates the login (password from BRAIN_API_DB_PASSWORD), allows it to connect to
# brain_db only, and grants SELECT on the eight read tables that already exist. The Brain's
# migrations grant the same list (brain/src/brain/grants.py), so whichever runs last, the result
# is the same. Credentials come from the environment, never from code.
#
# The SQL is fed to psql on stdin (a heredoc), never with -c: psql does not substitute
# :"var" / :'var' variables inside a -c string.
set -eu

: "${BRAIN_API_DB_USER:?BRAIN_API_DB_USER is not set}"
: "${BRAIN_API_DB_PASSWORD:?BRAIN_API_DB_PASSWORD is not set}"

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v api_user="$BRAIN_API_DB_USER" -v api_password="$BRAIN_API_DB_PASSWORD" <<-EOSQL
SELECT format('CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE', :'api_user')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'api_user') \gexec
SELECT format('ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD %L',
              :'api_user', :'api_password') \gexec
GRANT CONNECT ON DATABASE brain_db TO :"api_user";
REVOKE CONNECT ON DATABASE erp_db FROM :"api_user";

\connect brain_db
GRANT USAGE ON SCHEMA public TO :"api_user";
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM :"api_user";
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM :"api_user";
SELECT format('GRANT SELECT ON TABLE %I TO %I', t, :'api_user')
FROM unnest(ARRAY['risk_result', 'forecast', 'model_choice', 'model_health',
                  'anomaly', 'product_ref', 'sales_daily', 'job_run']) AS t
WHERE to_regclass(format('public.%I', t)) IS NOT NULL \gexec
-- Feature 004: writes on the proposal tables only (same list as brain/src/brain/grants.py).
SELECT format('GRANT %s ON TABLE %I TO %I', p, t, :'api_user')
FROM (VALUES ('proposal', 'SELECT, INSERT, UPDATE'),
             ('proposal_line', 'SELECT, INSERT'),
             ('proposal_live_product', 'SELECT, INSERT, DELETE'),
             ('proposal_attempt', 'SELECT, INSERT, UPDATE')) AS w(t, p)
WHERE to_regclass(format('public.%I', t)) IS NOT NULL \gexec
SELECT format('brain_api role %s: SELECT on %s', :'api_user',
              coalesce(string_agg(table_name, ', ' ORDER BY table_name), 'no tables yet'))
FROM information_schema.role_table_grants
WHERE grantee = :'api_user' AND privilege_type = 'SELECT';
SELECT format('brain_api role %s: writes on %s', :'api_user',
              coalesce(string_agg(DISTINCT table_name, ', ' ORDER BY table_name), 'no tables yet'))
FROM information_schema.role_table_grants
WHERE grantee = :'api_user' AND privilege_type IN ('INSERT', 'UPDATE', 'DELETE');
EOSQL
