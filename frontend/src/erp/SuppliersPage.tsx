import { EditOutlined, PlusOutlined } from "@ant-design/icons";
import { Button, Card, Form, Input, InputNumber, Modal, Table } from "antd";
import type { TableColumnsType } from "antd";
import { useState } from "react";
import { apiFetch } from "../api/client";
import type { Supplier } from "../api/types";
import { messageOf, useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { byNumber, byText, pagination } from "../components/table";

interface SupplierValues {
  name: string;
  lead_time_days: number;
}

type Editing = { mode: "add" } | { mode: "edit"; supplier: Supplier } | null;

interface ModalProps {
  editing: Exclude<Editing, null>;
  onClose: () => void;
  onSaved: () => void;
}

/** "Add supplier" and "Edit" share one modal form; the requests are the same as before. */
function SupplierModal({ editing, onClose, onSaved }: ModalProps) {
  const [form] = Form.useForm<SupplierValues>();
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const adding = editing.mode === "add";

  async function save(values: SupplierValues) {
    setSaving(true);
    setError(null);
    try {
      if (editing.mode === "add") {
        await apiFetch<Supplier>("/suppliers", { method: "POST", body: { ...values } });
      } else {
        await apiFetch<Supplier>(`/suppliers/${editing.supplier.supplier_id}`, {
          method: "PATCH",
          body: { ...values },
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
      title={adding ? "Add supplier" : `Edit ${editing.supplier.supplier_id}`}
      okText={adding ? "Add supplier" : "Save"}
      onOk={() => form.submit()}
      onCancel={onClose}
      confirmLoading={saving}
      mask={{ closable: false }}
      destroyOnHidden
    >
      <Form<SupplierValues>
        form={form}
        name="supplier"
        layout="vertical"
        initialValues={
          editing.mode === "add"
            ? { lead_time_days: 3 }
            : { name: editing.supplier.name, lead_time_days: editing.supplier.lead_time_days }
        }
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
          label="Lead time (days)"
          name="lead_time_days"
          rules={[{ required: true, message: "Enter a whole number of 1 or more" }]}
        >
          <InputNumber min={1} precision={0} style={{ inlineSize: "100%" }} />
        </Form.Item>
        <ErrorAlert error={error} />
      </Form>
    </Modal>
  );
}

// There is no delete control anywhere: nothing in the ERP is ever deleted (FR-022).
export function SuppliersPage() {
  const { data: suppliers, error, loading, reload } = useApiData<Supplier[]>("/suppliers");
  const [editing, setEditing] = useState<Editing>(null);

  const columns: TableColumnsType<Supplier> = [
    {
      title: "ID",
      dataIndex: "supplier_id",
      width: 90,
      sorter: byText((s) => s.supplier_id),
      defaultSortOrder: "ascend",
    },
    { title: "Name", dataIndex: "name", sorter: byText((s) => s.name) },
    {
      title: "Lead time (days)",
      dataIndex: "lead_time_days",
      align: "end",
      sorter: byNumber((s) => s.lead_time_days),
    },
    {
      title: "Actions",
      key: "actions",
      width: 110,
      render: (_, s) => (
        <Button
          size="small"
          icon={<EditOutlined aria-hidden />}
          aria-label={`Edit ${s.supplier_id}`}
          onClick={() => setEditing({ mode: "edit", supplier: s })}
        >
          Edit
        </Button>
      ),
    },
  ];

  return (
    <div className="page">
      <PageHeader
        title="Suppliers"
        subtitle="Supplier records and their lead times."
        actions={
          <Button
            type="primary"
            icon={<PlusOutlined aria-hidden />}
            onClick={() => setEditing({ mode: "add" })}
          >
            Add supplier
          </Button>
        }
      />
      <ErrorAlert error={error} />
      <Card>
        <Table<Supplier>
          rowKey="supplier_id"
          columns={columns}
          dataSource={suppliers ?? []}
          loading={loading}
          pagination={pagination}
        />
      </Card>
      {editing && (
        <SupplierModal
          editing={editing}
          onClose={() => setEditing(null)}
          onSaved={() => {
            setEditing(null);
            reload();
          }}
        />
      )}
    </div>
  );
}
