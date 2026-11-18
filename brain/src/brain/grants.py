"""What brain-api's login may read and write (D-45; feature 003 research R-16, P-7; feature 004
research R-04).

The same lists are applied by the Brain's migrations (here) and by the idempotent
postgres/init/02-brain-api-role.sh; tests check the two never differ.
"""

from sqlalchemy import Connection, text

API_READ_TABLES: tuple[str, ...] = (
    "risk_result",
    "forecast",
    "model_choice",
    "model_health",
    "anomaly",
    "product_ref",
    "sales_daily",
    "job_run",
)

# Feature 004: brain-api writes only the proposal tables. No DELETE on proposal, proposal_line or
# proposal_attempt, no UPDATE on proposal_line, and no TRUNCATE or REFERENCES anywhere.
API_WRITE_GRANTS: dict[str, tuple[str, ...]] = {
    "proposal": ("SELECT", "INSERT", "UPDATE"),
    "proposal_line": ("SELECT", "INSERT"),
    "proposal_live_product": ("SELECT", "INSERT", "DELETE"),
    "proposal_attempt": ("SELECT", "INSERT", "UPDATE"),
}


def role_exists(connection: Connection, role: str) -> bool:
    return bool(
        connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def _exists(connection: Connection, table: str) -> bool:
    return (
        connection.execute(text("SELECT to_regclass(:t)"), {"t": f"public.{table}"}).scalar()
        is not None
    )


def apply_api_grants(connection: Connection, role: str) -> None:
    """SELECT on the read tables and the proposal grants, nothing else, for `role` (as the tables'
    owner). Tables that don't exist yet (an earlier migration) are skipped."""
    quote = connection.dialect.identifier_preparer.quote
    who = quote(role)
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {who}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {who}"))
    connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {who}"))
    for table in API_READ_TABLES:
        connection.execute(text(f"GRANT SELECT ON TABLE {quote(table)} TO {who}"))
    for table, privileges in API_WRITE_GRANTS.items():
        if _exists(connection, table):
            connection.execute(
                text(f"GRANT {', '.join(privileges)} ON TABLE {quote(table)} TO {who}")
            )
