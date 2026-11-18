import { Card, Descriptions, Empty, Select, Space, Tag, Typography } from "antd";
import { useState } from "react";
import type { ForecastProduct, ProductForecast } from "../api/brainTypes";
import { BRAIN_BASE } from "../api/client";
import { useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import { ForecastChart, chartData } from "./ForecastChart";
import { MODEL_NAMES, SyntheticTag, anomalyText } from "./shared";

const percent = (wape: number | null) => (wape === null ? "not available" : `${(wape * 100).toFixed(1)}%`);

function ModelDetails({ body }: { body: ProductForecast }) {
  const m = body.model;
  return (
    <Descriptions
      size="small"
      column={{ xs: 1, md: 2, xl: 3 }}
      items={[
        {
          key: "model",
          label: "Chosen model",
          children: (
            <Space size={8}>
              <span>{MODEL_NAMES[m.chosen_model]}</span>
              {m.degraded && <Tag color="volcano">Degraded</Tag>}
            </Space>
          ),
        },
        { key: "run", label: "Run date", children: body.run_date },
        {
          key: "live",
          label: "Live WAPE",
          children: m.live_wape === null ? "not measured yet" : percent(m.live_wape),
        },
        { key: "sn", label: "Seasonal-naive backtest WAPE", children: percent(m.sn_backtest_wape) },
        {
          key: "lgbm",
          label: "LightGBM backtest WAPE",
          children: m.lgbm_eligible ? percent(m.lgbm_backtest_wape) : "not eligible (under 8 weeks of history)",
        },
      ]}
    />
  );
}

/** Brain → Forecasts: a product's last 28 closed days, its 14-day forecast and 80% range. */
export function ForecastsPage({ chartSize }: { chartSize?: { width: number; height: number } }) {
  const products = useApiData<ForecastProduct[]>("/forecasts", BRAIN_BASE);
  const [chosen, setChosen] = useState<string | null>(null);
  const list = products.data ?? [];
  const productId = chosen ?? list[0]?.product_id ?? null;
  const detail = useApiData<ProductForecast>(productId ? `/forecasts/${productId}` : null, BRAIN_BASE);
  const body = detail.data?.product_id === productId ? detail.data : null;

  return (
    <div className="page">
      <PageHeader
        title="Forecasts"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>Each product's last 28 closed days and the next 14 days, with an 80% range.</span>
          </Space>
        }
      />
      <ErrorAlert error={products.error ?? detail.error} />
      {products.data && list.length === 0 ? (
        <Card>
          <Empty description="No forecast yet: the first end-of-day run hasn't finished." />
        </Card>
      ) : (
        <Card
          title={
            <Select
              aria-label="Product"
              showSearch={{ optionFilterProp: "label" }}
              style={{ inlineSize: 360, maxInlineSize: "100%" }}
              loading={products.loading}
              value={productId ?? undefined}
              onChange={setChosen}
              options={list.map((p) => ({
                value: p.product_id,
                label: `${p.product_id} · ${p.product_name}`,
              }))}
            />
          }
          loading={!body && !detail.error}
        >
          {body && (
            <Space orientation="vertical" size={16} style={{ inlineSize: "100%" }}>
              <ForecastChart
                data={chartData(body.history, body.forecast)}
                today={body.forecast[0]?.target_date ?? body.run_date}
                size={chartSize}
              />
              <ModelDetails body={body} />
              <div>
                <Typography.Text strong>Anomalies on these days: </Typography.Text>
                {body.anomalies.length === 0 ? (
                  <Typography.Text type="secondary">none</Typography.Text>
                ) : (
                  <ul className="anomaly-list">
                    {body.anomalies.map((a) => (
                      <li key={`${a.business_date}-${a.scope}`}>
                        {anomalyText(a)} · {a.raised_risk ? "raised risk" : "did not raise risk"}
                      </li>
                    ))}
                  </ul>
                )}
              </div>
            </Space>
          )}
        </Card>
      )}
    </div>
  );
}
