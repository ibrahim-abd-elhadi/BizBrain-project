import { Card, Empty, Space, Table, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { Link } from "react-router";
import type { Proposal, ProposalList } from "../api/brainTypes";
import { BRAIN_BASE } from "../api/client";
import { useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { byNumber, pagination } from "../components/table";
import { ORIGIN_LABELS, ProposalStatusTag, SyntheticTag, cairoTime } from "./shared";

const units = (p: Proposal) => p.arguments.lines.reduce((sum, line) => sum + line.quantity, 0);

const columns: TableColumnsType<Proposal> = [
  {
    title: "Created",
    dataIndex: "created_at",
    width: 170,
    sorter: byNumber((p) => Date.parse(p.created_at)),
    render: (value: string) => <span className="nowrap">{cairoTime(value)}</span>,
  },
  {
    title: "Product(s)",
    key: "products",
    render: (_, p) => (
      <Link to={`/brain/proposals/${p.id}`}>{p.arguments.lines.map((line) => line.product_id).join(", ")}</Link>
    ),
  },
  {
    title: "Supplier",
    key: "supplier",
    render: (_, p) => `${p.supplier_name ?? "Unknown supplier"} (${p.supplier_id})`,
  },
  { title: "Quantity", key: "quantity", align: "end", render: (_, p) => units(p) },
  { title: "Origin", dataIndex: "origin", render: (value: Proposal["origin"]) => ORIGIN_LABELS[value] },
  {
    title: "Status",
    key: "status",
    render: (_, p) => <ProposalStatusTag status={p.status} sending={p.sending} />,
  },
  {
    title: "ERP order",
    dataIndex: "purchase_order_id",
    align: "end",
    render: (value: number | null) =>
      value === null ? <Typography.Text type="secondary">—</Typography.Text> : `#${value}`,
  },
];

/** Brain → Proposals: every proposal, newest first (FR-010). */
export function ProposalsPage() {
  const proposals = useApiData<ProposalList>("/proposals", BRAIN_BASE);
  const items = proposals.data?.items ?? [];

  return (
    <div className="page">
      <PageHeader
        title="Proposals"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>Purchase orders the Brain proposes. Nothing reaches the ERP until you approve one.</span>
          </Space>
        }
      />
      <ErrorAlert error={proposals.error} />
      <Card>
        {proposals.data && items.length === 0 ? (
          <Empty
            description={
              <span>
                No proposals yet. Create one from a recommendation on <Link to="/brain/risk">Risk and insights</Link>.
              </span>
            }
          />
        ) : (
          <Table<Proposal>
            rowKey="id"
            columns={columns}
            dataSource={items}
            loading={proposals.loading}
            pagination={pagination}
            scroll={{ x: 900 }}
          />
        )}
      </Card>
    </div>
  );
}
