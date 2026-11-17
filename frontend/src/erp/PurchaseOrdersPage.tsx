import { CheckOutlined } from "@ant-design/icons";
import { Button, Card, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { useMemo, useState } from "react";
import { apiFetch } from "../api/client";
import type { Product, PurchaseOrder, Supplier } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { StatusTag } from "../components/StatusTag";
import { byNumber, byText, pagination } from "../components/table";

const when = (value: string | null) => (value ? new Date(value).toLocaleString() : "—");

// Drafts come from the Brain through the Canonical API (feature 002), or by hand for testing.
// The manager can only confirm a draft: there is no create, edit, cancel or delete (FR-017,
// FR-022). Confirming treats the ordered quantities as received, so stock goes up (FR-024).
// Each order shows its supplier, and a Brain draft who approved it and when (feature 002 FR-029a).
export function PurchaseOrdersPage() {
  const { data: orders, error, loading, reload } = useApiData<PurchaseOrder[]>("/purchase-orders");
  const { data: products } = useApiData<Product[]>("/products");
  const { data: suppliers } = useApiData<Supplier[]>("/suppliers");
  const [actionError, setActionError] = useState<string | null>(null);
  const [confirming, setConfirming] = useState<number | null>(null);

  const names = useMemo(
    () => Object.fromEntries((products ?? []).map((p) => [p.product_id, p.name])),
    [products],
  );
  const supplierNames = useMemo(
    () => Object.fromEntries((suppliers ?? []).map((s) => [s.supplier_id, s.name])),
    [suppliers],
  );
  const supplierLabel = (o: PurchaseOrder) =>
    supplierNames[o.supplier_id] ? `${supplierNames[o.supplier_id]} (${o.supplier_id})` : o.supplier_id;

  async function confirm(poId: number) {
    setActionError(null);
    setConfirming(poId);
    try {
      await apiFetch<PurchaseOrder>(`/purchase-orders/${poId}/confirm`, { method: "POST" });
      reload();
    } catch (caught) {
      setActionError(messageOf(caught));
    } finally {
      setConfirming(null);
    }
  }

  const columns: TableColumnsType<PurchaseOrder> = [
    { title: "Order", dataIndex: "po_id", width: 90, sorter: byNumber((o) => o.po_id) },
    {
      title: "Status",
      dataIndex: "status",
      width: 120,
      render: (_, o) => <StatusTag status={o.status} />,
      filters: [
        { text: "draft", value: "draft" },
        { text: "confirmed", value: "confirmed" },
      ],
      onFilter: (value, o) => o.status === value,
    },
    {
      title: "Supplier",
      dataIndex: "supplier_id",
      render: (_, o) => supplierLabel(o),
      sorter: byText(supplierLabel),
    },
    {
      title: "Origin",
      key: "origin",
      render: (_, o) =>
        o.created_by === "agent" ? (
          <div className="origin">
            <Tag color="geekblue">Created by the Brain</Tag>
            {o.approval ? (
              <Typography.Text type="secondary" className="origin-approval">
                Approved by {o.approval.approved_by}, {when(o.approval.approved_at)}
              </Typography.Text>
            ) : null}
          </div>
        ) : (
          <span data-origin="human">—</span>
        ),
    },
    {
      title: "Created",
      dataIndex: "created_at",
      render: (value: string) => when(value),
      sorter: byNumber((o) => Date.parse(o.created_at)),
    },
    {
      title: "Confirmed",
      dataIndex: "confirmed_at",
      render: (value: string | null) => when(value),
    },
    {
      title: "Lines",
      key: "lines",
      render: (_, o) => (
        <ul className="lines">
          {o.lines.map((line) => (
            <li key={line.product_id}>
              {line.product_id}
              {names[line.product_id] ? ` ${names[line.product_id]}` : ""} × {line.quantity}
            </li>
          ))}
        </ul>
      ),
    },
    {
      title: "Actions",
      key: "actions",
      width: 130,
      render: (_, o) =>
        o.status === "draft" ? (
          <Button
            type="primary"
            size="small"
            icon={<CheckOutlined aria-hidden />}
            aria-label={`Confirm purchase order ${o.po_id}`}
            loading={confirming === o.po_id}
            onClick={() => void confirm(o.po_id)}
          >
            Confirm
          </Button>
        ) : null,
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Purchase orders"
        subtitle="Confirming a draft treats its quantities as received and adds them to stock."
      />
      <ErrorAlert error={actionError ?? error} />
      <Card>
        <Table<PurchaseOrder>
          rowKey="po_id"
          columns={columns}
          dataSource={orders ?? []}
          loading={loading}
          pagination={pagination}
          locale={{ emptyText: "No purchase orders yet." }}
        />
      </Card>
    </div>
  );
}
