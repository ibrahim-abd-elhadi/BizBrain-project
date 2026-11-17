"""Seed step 2: 4 synthetic suppliers and 20 synthetic generic-medicine products with starting stock.

Everything here is synthetic. Product names are generic names and strengths only (no brands).
PRODUCT_SPECS is exported so the sales-history step can use the same base demand per product.
"""

import math
from dataclasses import dataclass

from sqlalchemy.orm import Session

from erp.config import Settings
from erp.models import Product, Stock, Supplier


@dataclass(frozen=True)
class SupplierSpec:
    name: str
    lead_time_days: int


@dataclass(frozen=True)
class ProductSpec:
    name: str
    supplier_index: int  # index into SUPPLIER_SPECS
    pack_multiple: int  # one of {1, 5, 10, 12, 20, 30}
    k: int  # max_order_qty = pack_multiple x k, with k between 10 and 40
    base_daily_demand: int  # 3-60 units a day
    starting_cover_days: float

    @property
    def max_order_qty(self) -> int:
        return self.pack_multiple * self.k

    @property
    def starting_stock(self) -> int:
        return math.ceil(self.base_daily_demand * self.starting_cover_days)


SUPPLIER_SPECS: list[SupplierSpec] = [
    SupplierSpec("Alpha Pharma Supply", 2),
    SupplierSpec("Beta Medical Wholesale", 3),
    SupplierSpec("Gamma Drug Distribution", 5),
    SupplierSpec("Delta Health Trading", 7),
]

# Product IDs are assigned in this order on an empty database: the first entry is P001.
# P003, P011 and P017 start with less cover than their supplier's lead time, so the Brain has
# high-risk products to show later. At least 2 products have base demand >= 30 so the seed can
# plant its demand drops on them (a drop to 0 is then far below the previous 28 days).
PRODUCT_SPECS: list[ProductSpec] = [
    ProductSpec("Paracetamol 500 mg tablets", 0, 10, 40, 55, 14.0),  # P001
    ProductSpec("Ibuprofen 400 mg tablets", 0, 10, 30, 40, 12.0),  # P002
    ProductSpec("Amoxicillin 500 mg capsules", 3, 12, 20, 20, 3.0),  # P003: cover 3 < 7-day lead
    ProductSpec("Omeprazole 20 mg capsules", 1, 30, 20, 35, 15.0),  # P004
    ProductSpec("Metformin 500 mg tablets", 1, 30, 15, 28, 18.0),  # P005
    ProductSpec("Amlodipine 5 mg tablets", 2, 30, 15, 22, 16.0),  # P006
    ProductSpec("Atorvastatin 20 mg tablets", 2, 30, 12, 18, 20.0),  # P007
    ProductSpec("Cetirizine 10 mg tablets", 0, 10, 25, 25, 11.0),  # P008
    ProductSpec("Salbutamol 100 mcg inhaler", 3, 1, 40, 6, 17.0),  # P009
    ProductSpec("Loratadine 10 mg tablets", 1, 10, 20, 15, 13.0),  # P010
    ProductSpec("Azithromycin 250 mg tablets", 2, 5, 30, 10, 2.5),  # P011: cover 2.5 < 5-day lead
    ProductSpec("Diclofenac 50 mg tablets", 0, 20, 20, 30, 15.0),  # P012
    ProductSpec("Losartan 50 mg tablets", 1, 30, 12, 16, 19.0),  # P013
    ProductSpec("Levothyroxine 100 mcg tablets", 3, 30, 10, 8, 20.0),  # P014
    ProductSpec("Ciprofloxacin 500 mg tablets", 2, 10, 25, 12, 14.0),  # P015
    ProductSpec("Vitamin C 1000 mg effervescent tablets", 0, 20, 20, 45, 10.0),  # P016
    ProductSpec(
        "Oral rehydration salts sachets", 1, 5, 40, 14, 1.5
    ),  # P017: cover 1.5 < 3-day lead
    ProductSpec("Aspirin 75 mg tablets", 2, 30, 20, 24, 12.0),  # P018
    ProductSpec("Pantoprazole 40 mg tablets", 3, 20, 15, 9, 16.0),  # P019
    ProductSpec("Domperidone 10 mg tablets", 1, 12, 25, 4, 18.0),  # P020
]

LOW_COVER_PRODUCTS = ("P003", "P011", "P017")


def product_id_for(index: int) -> str:
    """The ID the database assigns to PRODUCT_SPECS[index] on an empty database."""
    return f"P{index + 1:03d}"


def seed_catalog(session: Session, settings: Settings) -> None:
    suppliers: list[Supplier] = []
    for spec in SUPPLIER_SPECS:
        supplier = Supplier(name=spec.name, lead_time_days=spec.lead_time_days)
        session.add(supplier)
        session.flush()  # one at a time, so IDs follow the list order (S001, S002, ...)
        suppliers.append(supplier)

    for spec in PRODUCT_SPECS:
        product = Product(
            name=spec.name,
            preferred_supplier_id=suppliers[spec.supplier_index].supplier_id,
            pack_multiple=spec.pack_multiple,
            max_order_qty=spec.max_order_qty,
        )
        session.add(product)
        session.flush()  # one at a time, so IDs follow the list order (P001, P002, ...)
        session.add(Stock(product_id=product.product_id, on_hand=spec.starting_stock))
    session.flush()
