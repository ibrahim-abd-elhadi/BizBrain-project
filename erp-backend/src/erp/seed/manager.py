"""Seed step 1: the single pharmacy-manager account (FR-010). Credentials come from configuration."""

from sqlalchemy.orm import Session

from erp.config import Settings
from erp.models import ManagerAccount
from erp.security import hash_password


class SeedConfigError(Exception):
    pass


def seed_manager(session: Session, settings: Settings) -> None:
    username = settings.erp_manager_username
    password = settings.erp_manager_password
    if not username or password is None or not password.get_secret_value():
        raise SeedConfigError(
            "ERP_MANAGER_USERNAME and ERP_MANAGER_PASSWORD must be set to seed the manager account"
        )
    session.add(
        ManagerAccount(username=username, password_hash=hash_password(password.get_secret_value()))
    )
    session.flush()
