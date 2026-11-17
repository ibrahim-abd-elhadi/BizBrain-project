import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { SalesPage } from "../erp/sales/SalesPage";

const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });

function mockApi(uploadResponse: Response) {
  const fetchMock = vi.fn(async (url: string, init?: RequestInit) => {
    if (url === "/api/v1/erp/sales/upload" && init?.method === "POST") return uploadResponse.clone();
    if (url.startsWith("/api/v1/erp/sales")) return json({ today: "2026-11-18", items: [] });
    if (url === "/api/v1/erp/products") return json([]);
    return json({ detail: "nope", code: "NOT_FOUND" }, 404);
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function renderSales() {
  return render(
    <MemoryRouter>
      <SalesPage />
    </MemoryRouter>,
  );
}

async function chooseAndUpload(content: string) {
  const file = new File([content], "totals.csv", { type: "text/csv" });
  await userEvent.upload(screen.getByLabelText(/csv file/i), file);
  await userEvent.click(screen.getByRole("button", { name: "Upload" }));
}

describe("Upload CSV panel", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("reports accepted, refused and overridden rows by line number", async () => {
    const fetchMock = mockApi(
      json({
        business_date: "2026-11-18",
        accepted: [
          { row: 2, product_id: "P001" },
          { row: 6, product_id: "P002" },
        ],
        refused: [
          { row: 4, code: "DAY_CLOSED", detail: "2026-11-17 is closed; only today (2026-11-18) can be uploaded" },
          { row: 5, code: "UNKNOWN_PRODUCT", detail: "Product 'P999' does not exist" },
        ],
        overridden: [{ row: 3, overridden_by_row: 6 }],
      }),
    );
    renderSales();
    await chooseAndUpload("business_date,product_id,units_sold,units_returned\n");

    const panel = await screen.findByRole("region", { name: "Upload CSV" });
    await within(panel).findByText(/Accepted: 2/);
    expect(within(panel).getByText(/Refused: 2/)).toBeInTheDocument();
    expect(within(panel).getByText(/Overridden: 1/)).toBeInTheDocument();

    const closedRow = within(panel).getByText("DAY_CLOSED").closest("tr") as HTMLElement;
    expect(within(closedRow).getByText("4")).toBeInTheDocument();
    expect(within(panel).getByText("UNKNOWN_PRODUCT")).toBeInTheDocument();
    expect(within(panel).getByText("row 3 overridden by row 6")).toBeInTheDocument();

    // The file is sent as multipart: the browser must set the Content-Type, not our code.
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST")!;
    const init = post[1] as RequestInit;
    expect(init.body).toBeInstanceOf(FormData);
    expect(new Headers(init.headers).has("Content-Type")).toBe(false);
  });

  it("shows the API's message when the whole file is refused", async () => {
    mockApi(json({ detail: "The first line must be exactly: business_date,product_id,units_sold,units_returned", code: "BAD_HEADER" }, 422));
    renderSales();
    await chooseAndUpload("wrong,header\n");

    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent(/first line must be exactly/));
    expect(screen.queryByText(/Accepted:/)).not.toBeInTheDocument();
  });

  it("only offers CSV files and keeps Upload disabled until one is chosen", async () => {
    mockApi(json({ business_date: "2026-11-18", accepted: [], refused: [], overridden: [] }));
    renderSales();
    const input = (await screen.findByLabelText(/csv file/i)) as HTMLInputElement;
    expect(input.accept).toBe(".csv");
    expect(screen.getByRole("button", { name: "Upload" })).toBeDisabled();
  });
});
