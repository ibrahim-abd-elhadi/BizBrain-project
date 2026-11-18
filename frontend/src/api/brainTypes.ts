// Types for the Brain API (specs/003-brain-intelligence/contracts/brain-api.openapi.yaml).

export type RiskLevel = "high" | "medium" | "low";
export type ReasonCode = "NO_SUPPLIER" | "OPEN_PO_UNAVAILABLE";
export type ModelKind = "seasonal_naive" | "lightgbm";

export interface Anomaly {
  kind: "spike" | "drop";
  scope: "intraday" | "closed";
  business_date: string;
  z: number;
  raised_risk: boolean;
}

export interface RiskInputs {
  forecast_over_lead: number | null;
  review_period_days: number;
  safety_stock: number | null;
  sd_28: number;
  mean_28: number;
  target: number | null;
  raw: number | null;
  pack_multiple: number;
  max_order_qty: number | null;
  forecast_run_date: string;
}

export interface RiskRow {
  product_id: string;
  product_name: string;
  risk: RiskLevel | null;
  base_risk: RiskLevel | null;
  raised_by_spike: boolean;
  days_of_cover: number | null;
  lead_time_days: number | null;
  available: number;
  open_po_qty: number | null;
  order_qty: number | null;
  reason_code: ReasonCode | null;
  inputs: RiskInputs;
  latest_anomaly: Anomaly | null;
  computed_at: string;
}

export interface RiskList {
  synthetic: true;
  results_exist: boolean;
  last_end_of_day: string | null;
  items: RiskRow[];
}

export interface ForecastProduct {
  product_id: string;
  product_name: string;
  chosen_model: ModelKind;
  degraded: boolean;
}

export interface ProductForecast {
  synthetic: true;
  product_id: string;
  product_name: string;
  run_date: string;
  model: {
    chosen_model: ModelKind;
    sn_backtest_wape: number | null;
    lgbm_backtest_wape: number | null;
    lgbm_eligible: boolean;
    degraded: boolean;
    live_wape: number | null;
  };
  history: { business_date: string; y_units: number }[];
  forecast: { target_date: string; yhat: number; low: number; high: number }[];
  anomalies: Anomaly[];
}
