"""Importing this package registers every model on Base.metadata (Alembic and the seed rely on it)."""

from erp.models.base import Base
from erp.models.manager_account import ManagerAccount
from erp.models.product import Product
from erp.models.stock import Stock
from erp.models.supplier import Supplier

__all__ = ["Base", "ManagerAccount", "Product", "Stock", "Supplier"]
