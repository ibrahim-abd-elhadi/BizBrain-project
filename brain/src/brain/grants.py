"""What brain-api's login may read (D-45, research R-16, P-7).

The same list is applied by the Brain's migrations (here) and by the idempotent
postgres/init/02-brain-api-role.sh; a test checks the two never differ.
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


def role_exists(connection: Connection, role: str) -> bool:
    return bool(
        connection.execute(text("SELECT 1 FROM pg_roles WHERE rolname = :r"), {"r": role}).scalar()
    )


def apply_api_grants(connection: Connection, role: str) -> None:
    """SELECT on the read tables, nothing else, for `role` (as the tables' owner)."""
    quote = connection.dialect.identifier_preparer.quote
    who = quote(role)
    connection.execute(text(f"GRANT USAGE ON SCHEMA public TO {who}"))
    connection.execute(text(f"REVOKE ALL ON ALL TABLES IN SCHEMA public FROM {who}"))
    connection.execute(text(f"REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM {who}"))
    for table in API_READ_TABLES:
        connection.execute(text(f"GRANT SELECT ON TABLE {quote(table)} TO {who}"))
