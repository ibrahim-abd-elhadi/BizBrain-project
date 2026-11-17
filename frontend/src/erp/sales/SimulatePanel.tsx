import { ThunderboltOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Form, Select, Table, Tag, Typography } from "antd";
import { useState } from "react";
import { apiFetch } from "../../api/client";
import type { Product, SimulateResult } from "../../api/types";
import { messageOf } from "../../api/useApiData";
import { ErrorAlert } from "../../components/ErrorAlert";

interface Props {
  products: Product[];
  /** Called after a run so the sales table can refresh. */
  onDone: () => void;
}

/** The sentence shown for a spike; a capped one says how far it got (FR-012). */
export function spikeMessage(spike: NonNullable<SimulateResult["spike"]>): string {
  if (spike.capped_by_stock) {
    return `Spike for ${spike.product_id} was capped by stock: reached ${spike.achieved_net_units} of ${spike.target_net_units} net units`;
  }
  return `Spike for ${spike.product_id} reached ${spike.achieved_net_units} net units (target ${spike.target_net_units})`;
}

// Runs the ERP's own Simulate Sales: it adds to today's totals. It is not a Brain job.
export function SimulatePanel({ products, onDone }: Props) {
  const [spikeId, setSpikeId] = useState<string | undefined>(undefined);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<SimulateResult | null>(null);

  async function run() {
    setBusy(true);
    setError(null);
    try {
      const outcome = await apiFetch<SimulateResult>("/sales/simulate", {
        method: "POST",
        body: spikeId ? { spike_product_id: spikeId } : {},
      });
      setResult(outcome);
      onDone();
    } catch (caught) {
      setResult(null);
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const changed = result?.products.length ?? 0;

  return (
    <section aria-label="Simulate Sales" className="panel-card">
      <Card title="Simulate Sales" className="panel-card">
        <Typography.Paragraph type="secondary">
          Adds a batch of sales to today&apos;s totals and lowers stock to match.
        </Typography.Paragraph>
        <Form layout="vertical">
          <Form.Item label="Spike product (optional)" htmlFor="spike-product">
            <Select
              id="spike-product"
              allowClear
              showSearch={{ optionFilterProp: "label" }}
              placeholder="No spike"
              value={spikeId}
              onChange={(value?: string) => setSpikeId(value)}
              options={products.map((p) => ({
                value: p.product_id,
                label: `${p.name} (${p.product_id})`,
              }))}
            />
          </Form.Item>
          <Button
            type="primary"
            icon={<ThunderboltOutlined aria-hidden />}
            loading={busy}
            onClick={() => void run()}
          >
            Simulate Sales
          </Button>
        </Form>

        {(error || result) && (
          <div className="panel-result" aria-live="polite">
            <ErrorAlert error={error} />
            {result && (
              <>
                <Alert
                  type={changed > 0 ? "success" : "info"}
                  showIcon
                  title={`Added to ${result.business_date}: ${
                    changed === 0 ? "nothing (no stock to sell)" : `${changed} product(s)`
                  }`}
                />
                {result.spike && (
                  <Alert
                    type={result.spike.capped_by_stock ? "warning" : "success"}
                    showIcon
                    title={spikeMessage(result.spike)}
                  />
                )}
                {changed > 0 && (
                  <Table
                    size="small"
                    rowKey="product_id"
                    dataSource={result.products}
                    pagination={changed > 5 ? { pageSize: 5, showSizeChanger: false } : false}
                    columns={[
                      { title: "Product", dataIndex: "product_id" },
                      {
                        title: "Sold",
                        dataIndex: "units_sold_added",
                        align: "end",
                        render: (n: number) => `+${n}`,
                      },
                      {
                        title: "Returned",
                        dataIndex: "units_returned_added",
                        align: "end",
                        render: (n: number) => `+${n}`,
                      },
                      {
                        title: "Note",
                        key: "note",
                        render: (_, p) =>
                          p.capped_by_stock ? <Tag color="orange">limited by stock</Tag> : null,
                      },
                    ]}
                  />
                )}
              </>
            )}
          </div>
        )}
      </Card>
    </section>
  );
}
