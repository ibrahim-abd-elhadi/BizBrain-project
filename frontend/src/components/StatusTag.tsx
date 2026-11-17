import { Tag } from "antd";

const COLORS = {
  open: "blue",
  closed: "green",
  draft: "gold",
  confirmed: "green",
} as const;

export type Status = keyof typeof COLORS;

/** Day status (open/closed) and purchase-order status (draft/confirmed) as colored tags. */
export function StatusTag({ status }: { status: Status }) {
  return <Tag color={COLORS[status]}>{status}</Tag>;
}
