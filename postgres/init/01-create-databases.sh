#!/bin/sh
# Creates the two logins and the two databases (README Section 1, research R-09).
# Runs once, on an empty data volume. All credentials come from the environment, never from code.
#
# The SQL is fed to psql on stdin (a heredoc), never with -c: psql does not substitute
# :"var" / :'var' variables inside a -c string.
set -eu

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname postgres \
  -v erp_user="$ERP_DB_USER" -v erp_password="$ERP_DB_PASSWORD" \
  -v brain_user="$BRAIN_DB_USER" -v brain_password="$BRAIN_DB_PASSWORD" <<-EOSQL
CREATE ROLE :"erp_user" LOGIN PASSWORD :'erp_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE ROLE :"brain_user" LOGIN PASSWORD :'brain_password' NOSUPERUSER NOCREATEDB NOCREATEROLE;
CREATE DATABASE erp_db OWNER :"erp_user";
CREATE DATABASE brain_db OWNER :"brain_user";
REVOKE CONNECT ON DATABASE erp_db, brain_db FROM PUBLIC;
EOSQL
