"""Readable ID formats: a letter and at least three digits (P001 ... P999, P1000, ...)."""

PRODUCT_ID_PATTERN = r"^P[0-9]{3,}$"
SUPPLIER_ID_PATTERN = r"^S[0-9]{3,}$"
