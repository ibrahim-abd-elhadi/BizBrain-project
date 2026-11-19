// Types for the Brain API (contracts/brain/brain-api.openapi.yaml).

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
  /** The risk_result this row shows; a proposal is built from it (feature 004). */
  recommendation_id: string;
  live_proposal: { id: string; status: "awaiting_approval" | "uncertain" } | null;
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

// Feature 004: proposals (contracts/brain/brain-api-proposals.openapi.yaml).

export type ProposalStatus = "awaiting_approval" | "uncertain" | "draft_created" | "failed" | "rejected";

export interface ProposalArguments {
  supplier_id: string;
  lines: { product_id: string; quantity: number }[];
}

export interface Proposal {
  synthetic: true;
  id: string;
  action: "create_purchase_order";
  origin: "recommendation" | "assistant";
  status: ProposalStatus;
  sending: boolean;
  supplier_id: string;
  supplier_name: string | null;
  arguments: ProposalArguments;
  arguments_sha256: string;
  recommendation_id: string | null;
  purchase_order_id: number | null;
  created_at: string;
}

export interface ProposalList {
  synthetic: true;
  items: Proposal[];
}

export interface RecommendationSummary {
  recommendation_id: string;
  product_id: string;
  risk: RiskLevel | null;
  days_of_cover: number | null;
  lead_time_days: number | null;
  order_qty: number | null;
  computed_at: string;
}

export interface ProposalAttempt {
  attempt_no: number;
  started_at: string;
  finished_at: string | null;
  outcome: "draft_created" | "uncertain" | "failed" | "not_sent" | null;
  http_status: number | null;
  erp_code: string | null;
  detail: string | null;
  purchase_order_id: number | null;
}

export interface ProposalDetail extends Proposal {
  lines: { product_id: string; product_name: string | null; quantity: number }[];
  recommendation: RecommendationSummary | null;
  newer_recommendation: RecommendationSummary | null;
  approval: { approved_by: string; approved_at: string } | null;
  failure: { code: string; reason: string } | null;
  attempts: ProposalAttempt[];
}

// ---- Feature 005: the assistant, the briefing and Why? (contracts/assistant/brain-api-assistant.openapi.yaml)

export type Language = "en" | "ar";
export type OfflineReason =
  | "no_key"
  | "unreachable"
  | "timeout"
  | "key_refused"
  | "model_not_found"
  | "rate_limited"
  | "server_error"
  | "refused";

export interface Availability {
  synthetic: true;
  available: boolean;
  reason: OfflineReason | null;
}

export interface ChatMessage {
  role: "manager" | "assistant";
  text: string;
  language?: Language;
}

export interface ChatRequest {
  messages: ChatMessage[];
}

export interface ChatProposal {
  id: string;
  path: string;
  status: "awaiting_approval";
  origin: "assistant";
  supplier_id: string;
  supplier_name: string;
  lines: { product_id: string; product_name: string; quantity: number }[];
}

export type ChatRefusalCode =
  | "PROPOSAL_PENDING"
  | "VALIDATION_ERROR"
  | "QUANTITY_NOT_GIVEN"
  | "NO_RECOMMENDED_QUANTITY"
  | "NO_RESULTS"
  | "UNKNOWN_PRODUCT"
  | "DIFFERENT_SUPPLIERS";

export interface ChatRefusal {
  code: ChatRefusalCode;
  detail: string;
  live_proposal_id: string | null;
  path: string | null;
}

export type CardCell = string | number | null;

/** Labeled figures built by code from the turn's tool results (never by the model). */
export interface DataCard {
  kind: "sales_summary" | "sales_history" | "risk" | "forecast";
  title: string;
  first_day: string | null;
  last_day: string | null;
  columns: string[];
  rows: CardCell[][];
  total: CardCell[] | null;
}

export interface ChatReply {
  synthetic: true;
  outcome: "answered" | "not_grounded" | "offline";
  offline_reason?: OfflineReason | null;
  reply: { text: string; language: Language } | null;
  proposal: ChatProposal | null;
  refusal: ChatRefusal | null;
  cards?: DataCard[];
}

export interface Briefing {
  synthetic: true;
  state: "none" | "offline" | "written";
  night: string | null;
  run_finished_at: string | null;
  text_en: string | null;
  text_ar: string | null;
}

export interface Explanation {
  synthetic: true;
  recommendation_id: string;
  product_id: string;
  language: Language;
  source: "assistant" | "template";
  text: string;
}
