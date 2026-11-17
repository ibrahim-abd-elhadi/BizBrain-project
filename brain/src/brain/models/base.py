from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Every Brain table lives in brain_db (constitution II). No tenant, branch or location column
    anywhere (constitution I)."""
