// Shapes returned by the ERP API (see specs/001-erp-core/contracts/erp-api.openapi.yaml).

export interface Supplier {
  supplier_id: string;
  name: string;
  lead_time_days: number;
}

export interface Product {
  product_id: string;
  name: string;
  preferred_supplier_id: string;
  pack_multiple: number;
  max_order_qty: number;
}

export interface StockRow {
  product_id: string;
  name: string;
  on_hand: number;
  updated_at: string;
}
