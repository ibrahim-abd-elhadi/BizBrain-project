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

export interface DailyTotal {
  product_id: string;
  business_date: string;
  units_sold: number;
  units_returned: number;
  net_units: number;
  day_status: "open" | "closed";
}

export interface SalesList {
  today: string; // the current business date in Africa/Cairo
  items: DailyTotal[];
}

export interface SimulateResult {
  business_date: string;
  products: {
    product_id: string;
    units_sold_added: number;
    units_returned_added: number;
    capped_by_stock: boolean;
  }[];
  spike: {
    product_id: string;
    target_net_units: number;
    achieved_net_units: number;
    capped_by_stock: boolean;
  } | null;
}

export interface PurchaseOrderLine {
  product_id: string;
  quantity: number;
}

// The approval block a draft from the Brain carries (feature 002, FR-029a).
export interface Approval {
  proposal_id: string;
  approved_by: string;
  approved_at: string;
  arguments_sha256: string;
}

export interface PurchaseOrder {
  po_id: number;
  status: "draft" | "confirmed";
  supplier_id: string;
  created_by: "human" | "agent";
  approval: Approval | null;
  created_at: string;
  updated_at: string;
  confirmed_at: string | null;
  lines: PurchaseOrderLine[];
}

export interface UploadResult {
  business_date: string;
  accepted: { row: number; product_id: string }[];
  refused: { row: number; code: string; detail: string }[];
  overridden: { row: number; overridden_by_row: number }[];
}
