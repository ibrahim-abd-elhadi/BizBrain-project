import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { describe, expect, it } from "vitest";
import { AppRoutes } from "../App";

function renderAt(path: string) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <AppRoutes />
    </MemoryRouter>,
  );
}

const ROUTES = ["/login", "/products", "/suppliers", "/inventory", "/sales", "/purchase-orders"];

describe("layout", () => {
  it.each(ROUTES)("shows the Synthetic data banner on %s", (route) => {
    sessionStorage.setItem("erp_token", "test-token"); // signed in, so every page renders
    renderAt(route);
    expect(screen.getByTestId("synthetic-banner")).toBeVisible();
    expect(screen.getByTestId("synthetic-banner")).toHaveTextContent("Synthetic data");
  });

  it("redirects an unauthenticated visit to /login (and still shows the banner)", () => {
    renderAt("/products");
    expect(screen.getByRole("heading", { name: "Sign in" })).toBeInTheDocument();
    expect(screen.queryByRole("heading", { name: "Products" })).not.toBeInTheDocument();
    expect(screen.getByTestId("synthetic-banner")).toBeVisible();
  });

  it("shows no menu until the manager is signed in", () => {
    renderAt("/login");
    expect(screen.queryByRole("navigation", { name: "Main" })).not.toBeInTheDocument();
  });
});
