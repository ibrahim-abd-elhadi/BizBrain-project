import { Card, Empty, Space, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { BRAIN_BASE } from "../api/client";
import type { RiskList, RiskRow } from "../api/brainTypes";
import { useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { byNumber, byText, pagination } from "../components/table";
import { AnomalyLabel, REASON_TEXT, RiskTag, SyntheticTag, cairoTime, days, riskLabel } from "./shared";

const LEVEL_ORDER = { high: 0, medium: 1, low: 2 } as const;
const dash = <Typography.Text type="secondary">—</Typography.Text>;

const columns: TableColumnsType<RiskRow> = [
  { title: "ID", dataIndex: "product_id", width: 80, sorter: byText((r) => r.product_id) },
  { title: "Name", dataIndex: "product_name", width: 230, sorter: byText((r) => r.product_name) },
  {
    title: "Risk",
    key: "risk",
    width: 110,
    sorter: byNumber((r) => (r.risk === null ? 3 : LEVEL_ORDER[r.risk])),
    render: (_, r) => (
      <Space size={4} orientation="vertical">
        <RiskTag level={r.risk} />
        {r.raised_by_spike && r.base_risk && r.risk !== r.base_risk && (
          <Typography.Text type="secondary" className="small-note">
            from {riskLabel(r.base_risk)}
          </Typography.Text>
        )}
      </Space>
    ),
  },
  {
    title: "Days of cover",
    dataIndex: "days_of_cover",
    align: "end",
    sorter: byNumber((r) => r.days_of_cover ?? Number.POSITIVE_INFINITY),
    render: (value: number | null) => (value === null ? "unlimited" : value.toFixed(2)),
  },
  {
    title: "Lead time",
    dataIndex: "lead_time_days",
    align: "end",
    render: (value: number | null) =>
      value === null ? dash : <span className="nowrap">{days(value)}</span>,
  },
  { title: "Available", dataIndex: "available", align: "end", sorter: byNumber((r) => r.available) },
  {
    title: "On order",
    dataIndex: "open_po_qty",
    align: "end",
    render: (value: number | null) => (value === null ? dash : value),
  },
  {
    title: "Recommended order",
    key: "order",
    align: "end",
    sorter: byNumber((r) => r.order_qty ?? -1),
    render: (_, r) =>
      r.reason_code ? (
        <Typography.Text type="warning">{REASON_TEXT[r.reason_code]}</Typography.Text>
      ) : (
        <Typography.Text strong={(r.order_qty ?? 0) > 0}>{r.order_qty}</Typography.Text>
      ),
  },
  {
    title: "Anomaly",
    key: "anomaly",
    width: 210,
    render: (_, r) => {
      const a = r.latest_anomaly;
      if (!a) return dash;
      return (
        <Space size={4} orientation="vertical">
          <AnomalyLabel a={a} />
          {a.raised_risk ? <Tag color="volcano">raised risk</Tag> : <Tag>did not raise risk</Tag>}
        </Space>
      );
    },
  },
  {
    title: "Computed at",
    dataIndex: "computed_at",
    render: (value: string) => <span className="nowrap">{cairoTime(value)}</span>,
  },
];

/** Brain → Risk and insights: the newest risk and recommendation per product (FR-029). */
export function RiskPage() {
  const risk = useApiData<RiskList>("/risk", BRAIN_BASE);
  const body = risk.data;

  return (
    <div className="page">
      <PageHeader
        title="Risk and insights"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>
              Stock-out risk and the recommended order for every product, highest risk first.
              {body?.last_end_of_day
                ? ` Last end-of-day run: ${cairoTime(body.last_end_of_day)}.`
                : ""}
            </span>
          </Space>
        }
      />
      <ErrorAlert error={risk.error} />
      <Card>
        {body && !body.results_exist ? (
          <Empty description="No risk results yet: the first end-of-day run hasn't finished." />
        ) : (
          <Table<RiskRow>
            rowKey="product_id"
            columns={columns}
            dataSource={body?.items ?? []}
            loading={risk.loading}
            pagination={pagination}
            scroll={{ x: 1100 }}
          />
        )}
      </Card>
    </div>
  );
}
