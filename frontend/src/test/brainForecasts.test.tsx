import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { chartData } from "../brain/ForecastChart";
import { ForecastsPage } from "../brain/ForecastsPage";
import { chooseOption, json } from "./antd";

const day = (offset: number) => {
  const d = new Date(Date.UTC(2026, 10, 18 + offset));
  return d.toISOString().slice(0, 10);
};

const HISTORY = Array.from({ length: 28 }, (_, i) => ({ business_date: day(i - 28), y_units: 18 + (i % 7) }));
const FORECAST = Array.from({ length: 14 }, (_, i) => ({
  target_date: day(i),
  yhat: 20 + (i % 7),
  low: 14 + (i % 7),
  high: 27 + (i % 7),
}));

const PRODUCTS = [
  { product_id: "P001", product_name: "Paracetamol 500 mg tablets", chosen_model: "seasonal_naive", degraded: false },
  { product_id: "P003", product_name: "Amoxicillin 500 mg capsules", chosen_model: "lightgbm", degraded: true },
];

const detail = (id: string, name: string, model: string, degraded: boolean) => ({
  synthetic: true,
  product_id: id,
  product_name: name,
  run_date: "2026-11-18",
  model: {
    chosen_model: model,
    sn_backtest_wape: 0.2877,
    lgbm_backtest_wape: 0.2361,
    lgbm_eligible: true,
    degraded,
    live_wape: degraded ? 0.41 : null,
  },
  history: HISTORY,
  forecast: FORECAST,
  anomalies: [{ kind: "spike", scope: "closed", business_date: day(-8), z: 6.1, raised_risk: false }],
});

function mockApi(products: unknown[] = PRODUCTS) {
  const routes: Record<string, unknown> = {
    "/api/v1/brain/forecasts": products,
    "/api/v1/brain/forecasts/P001": detail("P001", "Paracetamol 500 mg tablets", "seasonal_naive", false),
    "/api/v1/brain/forecasts/P003": detail("P003", "Amoxicillin 500 mg capsules", "lightgbm", true),
  };
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url) =>
    url in routes ? json(routes[url]) : json({ detail: "nope", code: "NOT_FOUND" }, 404),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderPage() {
  return render(
    <MemoryRouter>
      <ForecastsPage chartSize={{ width: 900, height: 320 }} />
    </MemoryRouter>,
  );
}

describe("Forecasts", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("builds 28 history points, 14 forecast points and the 80% band", () => {
    const data = chartData(HISTORY, FORECAST);
    expect(data).toHaveLength(42);
    expect(data.filter((d) => d.sales !== null)).toHaveLength(28);
    const ahead = data.filter((d) => d.forecast !== null);
    expect(ahead).toHaveLength(14);
    expect(ahead[0]).toMatchObject({ date: day(0), forecast: 20, band: [14, 27] });
    expect(data[0]).toMatchObject({ date: day(-28), sales: 18, forecast: null, band: null });
  });

  it("shows the chosen product's chart and model", async () => {
    const fetchMock = mockApi();
    renderPage();
    const select = await screen.findByRole("combobox", { name: /product/i });
    await chooseOption(select, "P003 · Amoxicillin 500 mg capsules");
    await waitFor(() =>
      expect(fetchMock.mock.calls.map(([url]) => url)).toContain("/api/v1/brain/forecasts/P003"),
    );
    expect(await screen.findByText("LightGBM")).toBeInTheDocument();
    expect(screen.getByText("23.6%")).toBeInTheDocument(); // the chosen model's backtest WAPE
    expect(screen.getByText("28.8%")).toBeInTheDocument(); // seasonal-naive's, for comparison
    expect(screen.getByText("Degraded")).toBeInTheDocument();
    expect(screen.getByText(/2026-11-18/)).toBeInTheDocument();

    const chart = await screen.findByTestId("forecast-chart");
    for (const label of ["Sales (last 28 days)", "Forecast", "80% range"]) {
      expect(chart).toHaveTextContent(label);
    }
    expect(chart).toHaveTextContent("Units per day");
    expect(screen.getByText(/spike on/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run|job|poll|train/i })).not.toBeInTheDocument();
  });

  it("says when there is no forecast yet", async () => {
    mockApi([]);
    renderPage();
    expect(await screen.findByText(/no forecast yet/i)).toBeInTheDocument();
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
  });
});
