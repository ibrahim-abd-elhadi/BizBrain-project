import { render, screen, waitFor, within } from "@testing-library/react";
import { Button } from "antd";
import { MemoryRouter } from "react-router";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AppRoutes } from "../App";
import { AppProviders, documentDirection } from "../AppProviders";
import { json, user } from "./antd";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

function stubApi() {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) =>
      url === "/api/v1/erp/auth/me"
        ? json({ username: "manager" })
        : url === "/api/v1/brain/risk"
          ? json({ synthetic: true, results_exist: false, last_end_of_day: null, items: [] })
          : json(url.startsWith("/api/v1/erp/sales") ? { today: "2026-11-18", items: [] } : []),
    ),
  );
}

const ROUTES = [
  "/login",
  "/products",
  "/suppliers",
  "/inventory",
  "/sales",
  "/purchase-orders",
  "/brain/risk",
  "/brain/forecasts",
];

describe("layout", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    document.documentElement.dir = "";
  });

  it.each(ROUTES)("shows the Synthetic data tag on %s", (route) => {
    sessionStorage.setItem("erp_token", "test-token"); // signed in, so every page renders
    stubApi();
    renderAt(route);
    expect(screen.getByTestId("synthetic-banner")).toBeVisible();
    expect(screen.getByTestId("synthetic-banner")).toHaveTextContent("Synthetic data");
  });

  it("redirects an unauthenticated visit to /login (and still shows the tag)", () => {
    renderAt("/products");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Products" })).not.toBeInTheDocument();
    expect(screen.getByTestId("synthetic-banner")).toBeVisible();
  });

  it("shows no sidebar, user or Sign out until the manager is signed in", () => {
    renderAt("/login");
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /sign out/i })).not.toBeInTheDocument();
    expect(screen.queryByTestId("signed-in-user")).not.toBeInTheDocument();
  });

  it("signed in: the header shows the user and Sign out, and the sidebar links every screen", async () => {
    sessionStorage.setItem("erp_token", "test-token");
    stubApi();
    renderAt("/inventory");

    expect(await screen.findByTestId("signed-in-user")).toHaveTextContent("manager");
    const nav = screen.getByRole("navigation", { name: "Main" });
    expect(within(nav).getAllByRole("link").map((a) => a.textContent)).toEqual([
      "Products",
      "Suppliers",
      "Inventory",
      "Sales",
      "Purchase orders",
      "Risk and insights",
      "Forecasts",
    ]);
    // The ERP screens and the Brain's read-only screens are two labelled groups.
    expect(within(nav).getByText("ERP")).toBeInTheDocument();
    expect(within(nav).getByText("Brain")).toBeInTheDocument();
    expect(within(nav).getByRole("link", { name: "Inventory" }).closest("li")).toHaveClass(
      "ant-menu-item-selected",
    );

    await user().click(screen.getByRole("button", { name: /sign out/i }));
    await waitFor(() => expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument());
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
    expect(sessionStorage.getItem("erp_token")).toBeNull();
  });

  it("login is a card with the sign-in form", () => {
    renderAt("/login");
    const heading = screen.getByRole("heading", { name: "Sign in" });
    expect(heading.closest(".ant-card")).not.toBeNull();
    expect(screen.getByLabelText("Username")).toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toBeInTheDocument();
  });
});

describe("right-to-left support at the root", () => {
  afterEach(() => {
    document.documentElement.dir = "";
  });

  it("is left to right by default and follows <html dir>", () => {
    expect(documentDirection()).toBe("ltr");
    document.documentElement.dir = "rtl";
    expect(documentDirection()).toBe("rtl");
  });

  it("switches Ant Design components to right to left", () => {
    render(
      <AppProviders direction="rtl">
        <Button>Save</Button>
      </AppProviders>,
    );
    expect(screen.getByRole("button", { name: "Save" })).toHaveClass("ant-btn-rtl");
  });
});
