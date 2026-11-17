import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { InventoryPage } from "../erp/InventoryPage";
import { ProductsPage } from "../erp/ProductsPage";
import { SuppliersPage } from "../erp/SuppliersPage";
import { json, openDialog, user } from "./antd";

const SUPPLIERS = [{ supplier_id: "S001", name: "Nile Pharma", lead_time_days: 3 }];
const product = (id: string, name: string, pack = 10, max = 400) => ({
  product_id: id,
  name,
  preferred_supplier_id: "S001",
  pack_multiple: pack,
  max_order_qty: max,
});
const PRODUCTS = [product("P001", "Paracetamol 500 mg")];
const INVENTORY = [
  { product_id: "P001", name: "Paracetamol 500 mg", on_hand: 120, updated_at: "2026-11-17T08:00:00Z" },
];

type Routes = Record<string, unknown>;

/** GETs answer from `routes`; writes are recorded and answered with `writeResponse`. */
function mockApi(routes: Routes = {}, writeResponse: unknown = {}) {
  const all: Routes = {
    "/api/v1/erp/suppliers": SUPPLIERS,
    "/api/v1/erp/products": PRODUCTS,
    "/api/v1/erp/inventory": INVENTORY,
    ...routes,
  };
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method && init.method !== "GET") return json(writeResponse, init.method === "POST" ? 201 : 200);
    if (!(url in all)) return json({ detail: "nope", code: "NOT_FOUND" }, 404);
    return json(all[url]);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const writes = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.mock.calls
    .filter(([, init]) => init?.method && init.method !== "GET")
    .map(([url, init]) => ({ url, method: init!.method, body: JSON.parse(String(init!.body)) }));

function renderPage(page: React.ReactElement) {
  return render(<MemoryRouter>{page}</MemoryRouter>);
}

function expectNoDeleteControl() {
  expect(screen.queryByRole("button", { name: /delete|remove/i })).not.toBeInTheDocument();
  expect(screen.queryByRole("link", { name: /delete|remove/i })).not.toBeInTheDocument();
}

const bodyRows = () => document.querySelectorAll(".ant-table-tbody tr.ant-table-row");

describe("catalog screens", () => {
  beforeEach(() => {
    sessionStorage.setItem("erp_token", "test-token");
  });
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("products page shows preferred supplier, pack multiple and maximum order quantity", async () => {
    mockApi();
    renderPage(<ProductsPage />);
    await screen.findByText(/Nile Pharma/);
    const row = screen.getByText("Paracetamol 500 mg").closest("tr") as HTMLElement;

    for (const header of [/preferred supplier/i, /pack multiple/i, /maximum order quantity/i]) {
      expect(screen.getByRole("columnheader", { name: header })).toBeInTheDocument();
    }
    expect(within(row).getByText("P001")).toBeInTheDocument();
    expect(within(row).getByText(/Nile Pharma/)).toBeInTheDocument();
    expect(within(row).getByText("10")).toBeInTheDocument();
    expect(within(row).getByText("400")).toBeInTheDocument();
    expectNoDeleteControl();
  });

  it("tables show 20 rows per page and sort by column", async () => {
    const many = Array.from({ length: 25 }, (_, i) =>
      product(`P${String(i + 1).padStart(3, "0")}`, `Product ${String.fromCharCode(90 - i)}`),
    );
    mockApi({ "/api/v1/erp/products": many });
    renderPage(<ProductsPage />);

    await screen.findByText("P001");
    expect(bodyRows()).toHaveLength(20);
    expect(screen.getByText("25 rows")).toBeInTheDocument();

    // Sorted by ID by default; sorting by name puts "Product B" (P025) first.
    expect(bodyRows()[0]).toHaveTextContent("P001");
    fireEvent.click(screen.getByRole("columnheader", { name: /^name/i }));
    await waitFor(() => expect(bodyRows()[0]).toHaveTextContent("P025"));
  });

  it("Add product opens a modal and sends the same request as before", async () => {
    const fetchMock = mockApi({}, product("P002", "Ibuprofen 400 mg"));
    renderPage(<ProductsPage />);
    await screen.findByText(/Nile Pharma/);

    await user().click(screen.getByRole("button", { name: "Add product" }));
    const dialog = await openDialog("Add product");
    await user().type(within(dialog).getByLabelText("Name"), "Ibuprofen 400 mg");
    await user().click(within(dialog).getByRole("button", { name: "Add product" }));

    await waitFor(() => expect(writes(fetchMock)).toHaveLength(1));
    expect(writes(fetchMock)[0]).toEqual({
      url: "/api/v1/erp/products",
      method: "POST",
      body: {
        name: "Ibuprofen 400 mg",
        preferred_supplier_id: "S001",
        pack_multiple: 10,
        max_order_qty: 100,
        starting_stock: 0,
      },
    });
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("a refused save keeps the modal open and shows the API's detail", async () => {
    const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
      if (init?.method === "PATCH")
        return json({ detail: "Maximum order quantity (5) cannot be below the pack multiple (10)", code: "MAX_BELOW_PACK" }, 422);
      return json(url.endsWith("/suppliers") ? SUPPLIERS : PRODUCTS);
    });
    vi.stubGlobal("fetch", fetchMock);
    renderPage(<ProductsPage />);
    await screen.findByText(/Nile Pharma/);

    await user().click(screen.getByRole("button", { name: "Edit P001" }));
    const dialog = await openDialog("Edit P001");
    expect(within(dialog).getByLabelText("Name")).toHaveValue("Paracetamol 500 mg");
    const max = within(dialog).getByLabelText("Maximum order quantity");
    await user().clear(max);
    await user().type(max, "5");
    await user().click(within(dialog).getByRole("button", { name: "Save" }));

    expect(await within(dialog).findByRole("alert")).toHaveTextContent(/cannot be below the pack multiple/);
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("suppliers page shows lead time, and Edit opens a modal that sends the same PATCH", async () => {
    const fetchMock = mockApi({}, { ...SUPPLIERS[0], lead_time_days: 6 });
    renderPage(<SuppliersPage />);
    const row = (await screen.findByText("Nile Pharma")).closest("tr") as HTMLElement;

    expect(screen.getByRole("columnheader", { name: /lead time/i })).toBeInTheDocument();
    expect(within(row).getByText("S001")).toBeInTheDocument();
    expect(within(row).getByText("3")).toBeInTheDocument();
    expectNoDeleteControl();

    await user().click(within(row).getByRole("button", { name: "Edit S001" }));
    const dialog = await openDialog("Edit S001");
    const lead = within(dialog).getByLabelText("Lead time (days)");
    await user().clear(lead);
    await user().type(lead, "6");
    await user().click(within(dialog).getByRole("button", { name: "Save" }));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        { url: "/api/v1/erp/suppliers/S001", method: "PATCH", body: { name: "Nile Pharma", lead_time_days: 6 } },
      ]),
    );
  });

  it("inventory page shows stock for the one location, with no location choice", async () => {
    mockApi();
    renderPage(<InventoryPage />);
    const row = (await screen.findByText("Paracetamol 500 mg")).closest("tr") as HTMLElement;

    expect(within(row).getByText("120")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: /location|branch/i })).not.toBeInTheDocument();
    expect(screen.queryByText(/location|branch/i)).not.toBeInTheDocument();
    expectNoDeleteControl();
  });

  it("inventory highlights stock below one pack, and stock at 0", async () => {
    mockApi({
      "/api/v1/erp/products": [product("P001", "Paracetamol"), product("P002", "Ibuprofen"), product("P003", "Amoxicillin", 12)],
      "/api/v1/erp/inventory": [
        { product_id: "P001", name: "Paracetamol", on_hand: 120, updated_at: "2026-11-17T08:00:00Z" },
        { product_id: "P002", name: "Ibuprofen", on_hand: 4, updated_at: "2026-11-17T08:00:00Z" },
        { product_id: "P003", name: "Amoxicillin", on_hand: 0, updated_at: "2026-11-17T08:00:00Z" },
      ],
    });
    renderPage(<InventoryPage />);
    await screen.findByText("Low stock");

    const rowOf = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;
    expect(rowOf("Paracetamol")).not.toHaveClass("stock-low");
    expect(within(rowOf("Paracetamol")).queryByText(/^(Low|Out of) stock$/)).not.toBeInTheDocument();
    expect(rowOf("Ibuprofen")).toHaveClass("stock-low");
    expect(within(rowOf("Ibuprofen")).getByText("Low stock")).toBeInTheDocument();
    expect(rowOf("Amoxicillin")).toHaveClass("stock-out");
    expect(within(rowOf("Amoxicillin")).getByText("Out of stock")).toBeInTheDocument();
  });

  it("Set stock opens a modal and sends the same PUT as before", async () => {
    const fetchMock = mockApi({}, { ...INVENTORY[0], on_hand: 25 });
    renderPage(<InventoryPage />);
    await screen.findByText("Paracetamol 500 mg");

    await user().click(screen.getByRole("button", { name: "Set stock for P001" }));
    const dialog = await openDialog("Set stock for P001");
    await user().type(within(dialog).getByLabelText("New stock"), "25");
    await user().click(within(dialog).getByRole("button", { name: "Set stock" }));

    await waitFor(() =>
      expect(writes(fetchMock)).toEqual([
        { url: "/api/v1/erp/inventory/P001", method: "PUT", body: { on_hand: 25 } },
      ]),
    );
  });
});
