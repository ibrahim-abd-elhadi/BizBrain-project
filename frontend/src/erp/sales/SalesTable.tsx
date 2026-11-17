import { Table } from "antd";
import type { TableColumnsType } from "antd";
import type { DailyTotal } from "../../api/types";
import { StatusTag } from "../../components/StatusTag";
import { byNumber, byText, pagination } from "../../components/table";

interface Props {
  items: DailyTotal[];
  /** product_id → name, for the Product column. */
  names: Record<string, string>;
  loading?: boolean;
}

// Read-only: daily totals are never edited or deleted from this table (FR-020, FR-022).
// Rows keep the API's order (newest first) until the manager sorts a column.
export function SalesTable({ items, names, loading }: Props) {
  const productLabel = (id: string) => (names[id] ? `${id} ${names[id]}` : id);

  const columns: TableColumnsType<DailyTotal> = [
    {
      title: "Business date",
      dataIndex: "business_date",
      width: 140,
      sorter: byText((t) => t.business_date),
    },
    {
      title: "Product",
      key: "product",
      render: (_, t) => productLabel(t.product_id),
      sorter: byText((t) => t.product_id),
    },
    {
      title: "Units sold",
      dataIndex: "units_sold",
      align: "end",
      sorter: byNumber((t) => t.units_sold),
    },
    {
      title: "Units returned",
      dataIndex: "units_returned",
      align: "end",
      sorter: byNumber((t) => t.units_returned),
    },
    {
      title: "Net units",
      dataIndex: "net_units",
      align: "end",
      sorter: byNumber((t) => t.net_units),
    },
    {
      title: "Status",
      dataIndex: "day_status",
      width: 110,
      render: (_, t) => <StatusTag status={t.day_status} />,
      filters: [
        { text: "open", value: "open" },
        { text: "closed", value: "closed" },
      ],
      onFilter: (value, t) => t.day_status === value,
    },
  ];

  return (
    <Table<DailyTotal>
      rowKey={(t) => `${t.business_date}/${t.product_id}`}
      columns={columns}
      dataSource={items}
      loading={loading}
      pagination={pagination}
      locale={{ emptyText: "No totals in this range." }}
    />
  );
}
