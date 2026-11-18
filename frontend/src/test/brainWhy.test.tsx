// Risk and insights → Why? (feature 005, US4; research R-09, R-15). Written first (T049).
import { render, screen, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RiskPage } from "../brain/RiskPage";
import { json, user } from "./antd";

const REC = "00000000-0000-4000-8000-000000000003";

const ROW = {
  product_id: "P003",
  product_name: "Amoxicillin 500 mg capsules",
  risk: "high",
  base_risk: "high",
  raised_by_spike: false,
  days_of_cover: 2.83,
  lead_time_days: 7,
  available: 60,
  open_po_qty: 0,
  order_qty: 108,
  reason_code: null,
  inputs: {
    forecast_over_lead: 145, review_period_days: 0, safety_stock: 23, sd_28: 1, mean_28: 20, target: 168,
    raw: 108, pack_multiple: 12, max_order_qty: 240, forecast_run_date: "2026-11-18",
  },
  latest_anomaly: null,
  computed_at: "2026-11-18T00:05:00Z",
  recommendation_id: REC,
  live_proposal: null,
};

const RISK = { synthetic: true, results_exist: true, last_end_of_day: "2026-11-18T00:05:03Z", items: [ROW] };

function explanation(language: "en" | "ar", source: "assistant" | "template") {
  return {
    synthetic: true,
    recommendation_id: REC,
    product_id: "P003",
    language,
    source,
    text:
      language === "en"
        ? "Amoxicillin 500 mg capsules (P003) has 2.83 days of cover against a 7-day lead time."
        : "يغطي مخزون Amoxicillin 500 mg capsules (P003) مدة 2.83 يوم.",
  };
}

function mount(source: "assistant" | "template") {
  const fetchMock = vi.fn(async (url: string) => {
    if (url.includes("/explanations/")) {
      const language = new URL(url, "http://x").searchParams.get("language") as "en" | "ar";
      return json(explanation(language, source));
    }
    return json(RISK);
  });
  vi.stubGlobal("fetch", fetchMock);
  render(
    <MemoryRouter>
      <RiskPage />
    </MemoryRouter>,
  );
  return fetchMock;
}

describe("Why? (US4)", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("opens a drawer with the English explanation, then Arabic right to left", async () => {
    const fetchMock = mount("assistant");
    const row = (await screen.findByText("Amoxicillin 500 mg capsules")).closest("tr") as HTMLElement;
    expect(within(row).getByRole("button", { name: /create proposal/i })).toBeInTheDocument();
    await user().click(within(row).getByRole("button", { name: "Why?" }));
    const drawer = await screen.findByRole("dialog");
    const english = await within(drawer).findByTestId("why-text");
    expect(english).toHaveTextContent("2.83 days of cover against a 7-day lead time");
    expect(english).toHaveAttribute("dir", "ltr");
    expect(within(drawer).queryByText("Plain version")).not.toBeInTheDocument();
    expect(fetchMock.mock.calls.some(([url]) => url.includes(`/explanations/${REC}?language=en`))).toBe(true);

    await user().click(within(drawer).getByText("Arabic"));
    const arabic = await within(drawer).findByText(/يغطي مخزون/);
    expect(arabic.closest("[data-testid='why-text']")).toHaveAttribute("dir", "rtl");
    expect(arabic.closest("[data-testid='why-text']")).toHaveAttribute("lang", "ar");
    expect(fetchMock.mock.calls.some(([url]) => url.includes(`/explanations/${REC}?language=ar`))).toBe(true);
    expect(within(drawer).getByRole("note")).toHaveTextContent("Synthetic data");
  });

  it("marks a template explanation as the plain version", async () => {
    mount("template");
    const row = (await screen.findByText("Amoxicillin 500 mg capsules")).closest("tr") as HTMLElement;
    await user().click(within(row).getByRole("button", { name: "Why?" }));
    const drawer = await screen.findByRole("dialog");
    expect(await within(drawer).findByText("Plain version")).toBeInTheDocument();
  });
});
