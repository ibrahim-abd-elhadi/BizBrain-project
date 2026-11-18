import { Tag } from "antd";
import type { Anomaly, ModelKind, ProposalStatus, ReasonCode, RiskLevel } from "../api/brainTypes";

/** Every Brain screen carries the label itself (README; FR-033), not only via the app shell. */
export function SyntheticTag() {
  return (
    <Tag color="gold" role="note">
      Synthetic data
    </Tag>
  );
}

const RISK_COLORS: Record<RiskLevel, string> = { high: "red", medium: "gold", low: "green" };
const RISK_LABELS: Record<RiskLevel, string> = { high: "High", medium: "Medium", low: "Low" };

export function riskLabel(level: RiskLevel): string {
  return RISK_LABELS[level];
}

export function RiskTag({ level }: { level: RiskLevel | null }) {
  if (level === null) return <Tag>No lead time</Tag>;
  return <Tag color={RISK_COLORS[level]}>{RISK_LABELS[level]}</Tag>;
}

export const REASON_TEXT: Record<ReasonCode, string> = {
  OPEN_PO_UNAVAILABLE: "Open orders couldn't be read",
  NO_SUPPLIER: "Supplier couldn't be read",
};

export const MODEL_NAMES: Record<ModelKind, string> = {
  seasonal_naive: "Seasonal-naive",
  lightgbm: "LightGBM",
};

export function anomalyText(a: Anomaly): string {
  const kind = a.kind === "spike" ? "Spike" : "Drop";
  const when = a.scope === "intraday" ? " (today, so far)" : "";
  return `${kind} on ${a.business_date}${when}, z ${a.z.toFixed(1)}`;
}

/** The anomaly as a table cell: the date never breaks across lines. */
export function AnomalyLabel({ a }: { a: Anomaly }) {
  const kind = a.kind === "spike" ? "Spike" : "Drop";
  const when = a.scope === "intraday" ? " (today, so far)" : "";
  return (
    <span>
      {kind} on <span className="nowrap">{a.business_date}</span>
      {when}, <span className="nowrap">z {a.z.toFixed(1)}</span>
    </span>
  );
}

/** A Cairo-time date and time, the pharmacy's clock. */
export function cairoTime(iso: string): string {
  return new Date(iso).toLocaleString("en-GB", {
    timeZone: "Africa/Cairo",
    dateStyle: "medium",
    timeStyle: "short",
  });
}

export const days = (n: number) => `${n} ${n === 1 ? "day" : "days"}`;

// Feature 004: proposal statuses, in words and colours (research R-12).
const STATUS_TAGS: Record<ProposalStatus, { label: string; color?: string }> = {
  awaiting_approval: { label: "Awaiting approval", color: "blue" },
  uncertain: { label: "Uncertain", color: "orange" },
  draft_created: { label: "Draft created", color: "green" },
  failed: { label: "Failed", color: "red" },
  rejected: { label: "Rejected" },
};

export function ProposalStatusTag({ status, sending = false }: { status: ProposalStatus; sending?: boolean }) {
  if (sending) return <Tag color="orange">Sending…</Tag>;
  const tag = STATUS_TAGS[status];
  return <Tag color={tag.color}>{tag.label}</Tag>;
}

export const ORIGIN_LABELS = { recommendation: "Recommendation", assistant: "Assistant" } as const;

/** The 64-character fingerprint in groups of 8, for reading it aloud or comparing by eye. */
export function groupedFingerprint(sha: string): string {
  return sha.match(/.{1,8}/g)?.join(" ") ?? sha;
}
