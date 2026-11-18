// Brain → Briefing (feature 005, US3; research R-10, R-15). Written first (T041).
import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { BriefingPage } from "../brain/BriefingPage";
import { json, user } from "./antd";

const body = (overrides: Record<string, unknown>) => ({
  synthetic: true,
  state: "written",
  night: "2026-11-17",
  run_finished_at: "2026-11-18T00:05:03Z",
  text_en: "Good morning. P003, P011 and P017 are high risk.",
  text_ar: "صباح الخير. المنتجات P003 وP011 وP017 مرتفعة الخطر.",
  ...overrides,
});

function show(response: unknown) {
  vi.stubGlobal("fetch", vi.fn(async () => json(response)));
  render(
    <MemoryRouter>
      <BriefingPage />
    </MemoryRouter>,
  );
}

describe("Briefing (US3)", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  it("says there is no briefing yet before the first night", async () => {
    show(body({ state: "none", night: null, run_finished_at: null, text_en: null, text_ar: null }));
    expect(await screen.findByText(/no briefing yet/i)).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Synthetic data");
  });

  it("shows Assistant offline, and no text, when that night's briefing couldn't be written", async () => {
    show(body({ state: "offline", text_en: null, text_ar: null }));
    expect(await screen.findByText("Assistant offline")).toBeInTheDocument();
    expect(screen.queryByTestId("briefing-text")).not.toBeInTheDocument();
  });

  it("shows the English briefing with its night, and Arabic right to left on the switch", async () => {
    show(body({}));
    const english = await screen.findByTestId("briefing-text");
    expect(english).toHaveTextContent("Good morning. P003, P011 and P017 are high risk.");
    expect(english).toHaveAttribute("dir", "ltr");
    expect(screen.getByText(/2026-11-17/)).toBeInTheDocument();
    expect(screen.getByRole("heading", { name: "Morning briefing" })).toBeInTheDocument();

    await user().click(screen.getByText("Arabic"));
    const arabic = await screen.findByTestId("briefing-text");
    expect(arabic).toHaveTextContent("صباح الخير");
    expect(arabic).toHaveAttribute("dir", "rtl");
    expect(arabic).toHaveAttribute("lang", "ar");
    // The screen itself stays English (FR-001a).
    expect(screen.getByRole("heading", { name: "Morning briefing" })).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Synthetic data");
  });
});
