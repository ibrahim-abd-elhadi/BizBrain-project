import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PurchaseOrdersPage } from "../erp/PurchaseOrdersPage";
import { user } from "./antd";

const PRODUCTS = [
  { product_id: "P001", name: "Paracetamol 500 mg", preferred_supplier_id: "S001", pack_multiple: 10, max_order_qty: 400 },
  { product_id: "P002", name: "Ibuprofen 400 mg", preferred_supplier_id: "S001", pack_multiple: 10, max_order_qty: 300 },
];

let orders: unknown[];

function mockApi() {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    const ok = (body: unknown) =>
      new Response(JSON.stringify(body), { status: 200, headers: { "Content-Type": "application/json" } });
    if (url === "/api/v1/erp/products") return ok(PRODUCTS);
    if (url === "/api/v1/erp/purchase-orders" && !init?.method) return ok(orders);
    if (url === "/api/v1/erp/purchase-orders/7/confirm" && init?.method === "POST") {
      orders = [
        { po_id: 7, status: "confirmed", created_at: "2026-11-18T08:00:00Z", confirmed_at: "2026-11-18T09:00:00Z", lines: [{ product_id: "P001", quantity: 60 }] },
        orders[1],
      ];
      return ok(orders[0]);
    }
    return new Response(JSON.stringify({ detail: "nope", code: "NOT_FOUND" }), { status: 404 });
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("purchase orders screen", () => {
  beforeEach(() => {
    sessionStorage.setItem("erp_token", "test-token");
    orders = [
      { po_id: 7, status: "draft", created_at: "2026-11-18T08:00:00Z", confirmed_at: null, lines: [{ product_id: "P001", quantity: 60 }] },
      { po_id: 6, status: "confirmed", created_at: "2026-11-17T08:00:00Z", confirmed_at: "2026-11-17T09:00:00Z", lines: [{ product_id: "P002", quantity: 30 }] },
    ];
  });
  afterEach(() => vi.unstubAllGlobals());

  it("shows status and lines, and offers Confirm on drafts only", async () => {
    mockApi();
    render(
      <MemoryRouter>
        <PurchaseOrdersPage />
      </MemoryRouter>,
    );

    const draftRow = (await screen.findByText("draft")).closest("tr") as HTMLElement;
    const confirmedRow = screen.getByText("confirmed").closest("tr") as HTMLElement;

    expect(within(draftRow).getByText(/P001/)).toBeInTheDocument();
    expect(within(draftRow).getByText(/60/)).toBeInTheDocument();
    expect(within(draftRow).getByRole("button", { name: /confirm/i })).toBeInTheDocument();
    expect(within(confirmedRow).queryByRole("button")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /delete|remove/i })).not.toBeInTheDocument();
  });

  it("confirms a draft and refreshes the list", async () => {
    const fetchMock = mockApi();
    render(
      <MemoryRouter>
        <PurchaseOrdersPage />
      </MemoryRouter>,
    );

    await user().click(await screen.findByRole("button", { name: /confirm/i }));

    await waitFor(() => expect(screen.queryByRole("button", { name: /confirm/i })).not.toBeInTheDocument());
    expect(screen.getAllByText("confirmed")).toHaveLength(2);
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/v1/erp/purchase-orders/7/confirm",
      expect.objectContaining({ method: "POST" }),
    );
  });
  it("shows draft and confirmed as colored tags", async () => {
    mockApi();
    render(
      <MemoryRouter>
        <PurchaseOrdersPage />
      </MemoryRouter>,
    );
    const draft = await screen.findByText("draft", { selector: ".ant-tag" });
    const confirmed = screen.getByText("confirmed", { selector: ".ant-tag" });
    expect(draft.className).toMatch(/gold/);
    expect(confirmed.className).toMatch(/green/);
  });
});
