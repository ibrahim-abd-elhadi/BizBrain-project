import { Button, Card, Form, InputNumber, Modal, Space, Table, Tag, Typography } from "antd";
import type { TableColumnsType } from "antd";
import { useState } from "react";
import { apiFetch } from "../api/client";
import type { Product, StockRow } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { byNumber, byText, pagination } from "../components/table";

type Level = "out" | "low" | "ok";

/**
 * An ERP-only rule from data the ERP holds: 0 is out of stock, below one pack (the product's pack
 * multiple) is low. Stock-out *risk* from cover and lead time is the Brain's job (README 4.3).
 */
export function stockLevel(onHand: number, packMultiple: number | undefined): Level {
  if (onHand === 0) return "out";
  if (packMultiple !== undefined && onHand < packMultiple) return "low";
  return "ok";
}

interface SetStockProps {
  row: StockRow;
  onClose: () => void;
  onSaved: () => void;
}

function SetStockModal({ row, onClose, onSaved }: SetStockProps) {
  const [form] = Form.useForm<{ on_hand: number }>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function save({ on_hand }: { on_hand: number }) {
    setSaving(true);
    setError(null);
    try {
      await apiFetch<StockRow>(`/inventory/${row.product_id}`, {
        method: "PUT",
        body: { on_hand },
      });
      onSaved();
    } catch (caught) {
      setError(messageOf(caught));
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      title={`Set stock for ${row.product_id}`}
      okText="Set stock"
      onOk={() => form.submit()}
      onCancel={onClose}
      confirmLoading={saving}
      mask={{ closable: false }}
      destroyOnHidden
    >
      <Typography.Paragraph type="secondary">
        {row.name}: {row.on_hand} on hand now.
      </Typography.Paragraph>
      <Form<{ on_hand: number }>
        form={form}
        name="set-stock"
        layout="vertical"
        onFinish={(values) => void save(values)}
      >
        <Form.Item
          label="New stock"
          name="on_hand"
          rules={[{ required: true, message: "Enter a whole number of 0 or more" }]}
        >
          <InputNumber min={0} precision={0} autoFocus style={{ inlineSize: "100%" }} />
        </Form.Item>
        <ErrorAlert error={error} />
      </Form>
    </Modal>
  );
}

// Stock at the pharmacy: one set of numbers, no place or branch to choose (FR-005).
export function InventoryPage() {
  const stock = useApiData<StockRow[]>("/inventory");
  const products = useApiData<Product[]>("/products");
  const [settingFor, setSettingFor] = useState<StockRow | null>(null);

  const packOf = Object.fromEntries((products.data ?? []).map((p) => [p.product_id, p.pack_multiple]));
  const levelOf = (row: StockRow) => stockLevel(row.on_hand, packOf[row.product_id]);

  const columns: TableColumnsType<StockRow> = [
    {
      title: "ID",
      dataIndex: "product_id",
      width: 90,
      sorter: byText((r) => r.product_id),
      defaultSortOrder: "ascend",
    },
    { title: "Name", dataIndex: "name", sorter: byText((r) => r.name) },
    {
      title: "On hand",
      dataIndex: "on_hand",
      align: "end",
      sorter: byNumber((r) => r.on_hand),
      filters: [{ text: "Low or out of stock", value: "attention" }],
      onFilter: (_, row) => levelOf(row) !== "ok",
      render: (_, row) => {
        const level = levelOf(row);
        return (
          <Space size={8}>
            {level === "out" && <Tag color="red">Out of stock</Tag>}
            {level === "low" && <Tag color="orange">Low stock</Tag>}
            <span>{row.on_hand}</span>
          </Space>
        );
      },
    },
    {
      title: "Last updated",
      dataIndex: "updated_at",
      render: (value: string) => new Date(value).toLocaleString(),
      sorter: byNumber((r) => Date.parse(r.updated_at)),
    },
    {
      title: "Actions",
      key: "actions",
      width: 130,
      render: (_, row) => (
        <Button
          size="small"
          aria-label={`Set stock for ${row.product_id}`}
          onClick={() => setSettingFor(row)}
        >
          Set stock
        </Button>
      ),
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Inventory"
        subtitle="Stock on hand. Rows are highlighted when stock is below one pack (the product's pack multiple), and when it is 0."
      />
      <ErrorAlert error={stock.error ?? products.error} />
      <Card>
        <Table<StockRow>
          rowKey="product_id"
          columns={columns}
          dataSource={stock.data ?? []}
          loading={stock.loading}
          pagination={pagination}
          rowClassName={(row) => {
            const level = levelOf(row);
            return level === "ok" ? "" : `stock-${level}`;
          }}
        />
      </Card>
      {settingFor && (
        <SetStockModal
          row={settingFor}
          onClose={() => setSettingFor(null)}
          onSaved={() => {
            setSettingFor(null);
            stock.reload();
          }}
        />
      )}
    </div>
  );
}
