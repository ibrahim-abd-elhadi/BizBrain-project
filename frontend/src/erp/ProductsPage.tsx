import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, InputNumber, Modal, Select, Table } from "antd";
import type { TableColumnsType } from "antd";
import { useState } from "react";
import { apiFetch } from "../api/client";
import type { Product, Supplier } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { byNumber, byText, pagination } from "../components/table";

interface ProductValues {
  name: string;
  preferred_supplier_id: string;
  pack_multiple: number;
  max_order_qty: number;
  starting_stock?: number;
}

type Editing = { mode: "add" } | { mode: "edit"; product: Product } | null;

interface ModalProps {
  editing: Exclude<Editing, null>;
  suppliers: Supplier[];
  onClose: () => void;
  onSaved: () => void;
}

/** "Add product" and "Edit" share one modal form; the requests are the same as before. */
function ProductModal({ editing, suppliers, onClose, onSaved }: ModalProps) {
  const [form] = Form.useForm<ProductValues>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const adding = editing.mode === "add";

  const initialValues: Partial<ProductValues> =
    editing.mode === "add"
      ? {
          preferred_supplier_id: suppliers[0]?.supplier_id,
          pack_multiple: 10,
          max_order_qty: 100,
          starting_stock: 0,
        }
      : {
          name: editing.product.name,
          preferred_supplier_id: editing.product.preferred_supplier_id,
          pack_multiple: editing.product.pack_multiple,
          max_order_qty: editing.product.max_order_qty,
        };

  async function save(values: ProductValues) {
    setSaving(true);
    setError(null);
    try {
      if (editing.mode === "add") {
        await apiFetch<Product>("/products", {
          method: "POST",
          body: { ...values, starting_stock: values.starting_stock ?? 0 },
        });
      } else {
        await apiFetch<Product>(`/products/${editing.product.product_id}`, {
          method: "PATCH",
          body: {
            name: values.name,
            preferred_supplier_id: values.preferred_supplier_id,
            pack_multiple: values.pack_multiple,
            max_order_qty: values.max_order_qty,
          },
        });
      }
      onSaved();
    } catch (caught) {
      setError(messageOf(caught));
      setSaving(false);
    }
  }

  return (
    <Modal
      open
      title={adding ? "Add product" : `Edit ${editing.product.product_id}`}
      okText={adding ? "Add product" : "Save"}
      onOk={() => form.submit()}
      onCancel={onClose}
      confirmLoading={saving}
      mask={{ closable: false }}
      destroyOnHidden
    >
      <Form<ProductValues>
        form={form}
        name="product"
        layout="vertical"
        initialValues={initialValues}
        onFinish={(values) => void save(values)}
      >
        <Form.Item
          label="Name"
          name="name"
          rules={[
            { required: true, whitespace: true, message: "Enter a name" },
            { max: 120, message: "Use 120 characters or fewer" },
          ]}
        >
          <Input autoFocus />
        </Form.Item>
        <Form.Item
          label="Preferred supplier"
          name="preferred_supplier_id"
          rules={[{ required: true, message: "Choose a supplier" }]}
        >
          <Select
            showSearch={{ optionFilterProp: "label" }}
            options={suppliers.map((s) => ({
              value: s.supplier_id,
              label: `${s.name} (${s.supplier_id})`,
            }))}
          />
        </Form.Item>
        <Form.Item
          label="Pack multiple"
          name="pack_multiple"
          rules={[{ required: true, message: "Enter a whole number of 1 or more" }]}
        >
          <InputNumber min={1} precision={0} style={{ inlineSize: "100%" }} />
        </Form.Item>
        <Form.Item
          label="Maximum order quantity"
          name="max_order_qty"
          rules={[{ required: true, message: "Enter a whole number of 1 or more" }]}
        >
          <InputNumber min={1} precision={0} style={{ inlineSize: "100%" }} />
        </Form.Item>
        {adding && (
          <Form.Item label="Starting stock (optional)" name="starting_stock">
            <InputNumber min={0} precision={0} style={{ inlineSize: "100%" }} />
          </Form.Item>
        )}
        <ErrorAlert error={error} />
      </Form>
    </Modal>
  );
}

// There is no delete control anywhere: nothing in the ERP is ever deleted (FR-022).
export function ProductsPage() {
  const products = useApiData<Product[]>("/products");
  const suppliers = useApiData<Supplier[]>("/suppliers");
  const [editing, setEditing] = useState<Editing>(null);

  const supplierLabel = (id: string) => {
    const found = suppliers.data?.find((s) => s.supplier_id === id);
    return found ? `${found.name} (${id})` : id;
  };

  const columns: TableColumnsType<Product> = [
    {
      title: "ID",
      dataIndex: "product_id",
      width: 90,
      sorter: byText((p) => p.product_id),
      defaultSortOrder: "ascend",
    },
    { title: "Name", dataIndex: "name", sorter: byText((p) => p.name) },
    {
      title: "Preferred supplier",
      key: "supplier",
      render: (_, p) => supplierLabel(p.preferred_supplier_id),
      sorter: byText((p) => supplierLabel(p.preferred_supplier_id)),
    },
    {
      title: "Pack multiple",
      dataIndex: "pack_multiple",
      align: "end",
      sorter: byNumber((p) => p.pack_multiple),
    },
    {
      title: "Maximum order quantity",
      dataIndex: "max_order_qty",
      align: "end",
      sorter: byNumber((p) => p.max_order_qty),
    },
    {
      title: "Actions",
      key: "actions",
      width: 110,
      render: (_, p) => (
        <Button
          size="small"
          icon={<EditOutlined aria-hidden />}
          aria-label={`Edit ${p.product_id}`}
          onClick={() => setEditing({ mode: "edit", product: p })}
        >
          Edit
        </Button>
      ),
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Products"
        subtitle="The product catalog: preferred supplier, pack multiple and maximum order quantity."
        actions={
          <Button
            type="primary"
            icon={<PlusOutlined aria-hidden />}
            onClick={() => setEditing({ mode: "add" })}
            disabled={!suppliers.data}
          >
            Add product
          </Button>
        }
      />
      <ErrorAlert error={products.error ?? suppliers.error} />
      <Card>
        <Table<Product>
          rowKey="product_id"
          columns={columns}
          dataSource={products.data ?? []}
          loading={products.loading}
          pagination={pagination}
        />
      </Card>
      {editing && (
        <ProductModal
          editing={editing}
          suppliers={suppliers.data ?? []}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            products.reload();
          }}
        />
      )}
    </div>
  );
}
