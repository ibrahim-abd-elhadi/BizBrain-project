import { Card, Col, Form, Input, Row, Select } from "antd";
import { useMemo, useState } from "react";
import type { Product, SalesList } from "../../api/types";
import { useApiData } from "../../api/useApiData";
import { ErrorAlert } from "../../components/ErrorAlert";
import { PageHeader } from "../../components/PageHeader";
import { SalesTable } from "./SalesTable";
import { SimulatePanel } from "./SimulatePanel";
import { UploadPanel } from "./UploadPanel";

interface Filters {
  product?: string;
  from?: string;
  to?: string;
}

// Daily totals per product and Cairo business date, newest first (FR-020), with the Simulate Sales
// and Upload CSV panels above them. Both panels refresh the table after they run.
export function SalesPage() {
  const [filters, setFilters] = useState<Filters>({});

  const query = new URLSearchParams();
  if (filters.product) query.set("product_id", filters.product);
  if (filters.from) query.set("from", filters.from);
  if (filters.to) query.set("to", filters.to);
  const path = query.size > 0 ? `/sales?${query.toString()}` : "/sales";

  const { data: sales, error, loading, reload } = useApiData<SalesList>(path);
  const { data: products } = useApiData<Product[]>("/products");

  const names = useMemo(
    () => Object.fromEntries((products ?? []).map((p) => [p.product_id, p.name])),
    [products],
  );

  return (
    <div className="page">
      <PageHeader
        title="Sales"
        subtitle={
          sales && (
            <>
              Today in Cairo: <strong data-testid="today-cairo">{sales.today}</strong>
            </>
          )
        }
      />

      <Row gutter={[16, 16]} data-testid="sales-panels">
        <Col xs={24} xl={12}>
          <SimulatePanel products={products ?? []} onDone={reload} />
        </Col>
        <Col xs={24} xl={12}>
          <UploadPanel onDone={reload} />
        </Col>
      </Row>

      <Card title="Daily totals">
        <Form<Filters>
          name="sales-filter"
          layout="inline"
          className="filters"
          aria-label="Filter sales"
          onValuesChange={(_, all) =>
            setFilters({
              product: all.product || undefined,
              from: all.from || undefined,
              to: all.to || undefined,
            })
          }
        >
          <Form.Item label="Product" name="product">
            <Select
              allowClear
              showSearch={{ optionFilterProp: "label" }}
              placeholder="All products"
              style={{ inlineSize: 300 }}
              options={(products ?? []).map((p) => ({
                value: p.product_id,
                label: `${p.name} (${p.product_id})`,
              }))}
            />
          </Form.Item>
          <Form.Item label="From" name="from">
            <Input type="date" />
          </Form.Item>
          <Form.Item label="To" name="to">
            <Input type="date" />
          </Form.Item>
        </Form>
        <div className="table-block">
          <ErrorAlert error={error} />
          <SalesTable items={sales?.items ?? []} names={names} loading={loading} />
        </div>
      </Card>
    </div>
  );
}
