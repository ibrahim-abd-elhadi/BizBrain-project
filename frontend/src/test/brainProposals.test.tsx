import { render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes, useParams } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ProposalDetailPage } from "../brain/ProposalDetailPage";
import { ProposalsPage } from "../brain/ProposalsPage";
import { RiskPage } from "../brain/RiskPage";
import { json, user } from "./antd";

const REC = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const PROPOSAL_ID = "11111111-1111-4111-8111-111111111111";

type Row = Record<string, unknown>;
const row = (id: string, name: string, overrides: Row = {}): Row => ({
  product_id: id,
  product_name: name,
  risk: "low",
  base_risk: "low",
  raised_by_spike: false,
  days_of_cover: 15.5,
  lead_time_days: 3,
  available: 300,
  open_po_qty: 0,
  order_qty: 0,
  reason_code: null,
  inputs: {
    forecast_over_lead: 10, review_period_days: 0, safety_stock: 5, sd_28: 1, mean_28: 3, target: 15,
    raw: -285, pack_multiple: 1, max_order_qty: null, forecast_run_date: "2026-11-18",
  },
  latest_anomaly: null,
  computed_at: "2026-11-18T00:05:00Z",
  recommendation_id: REC(Number(id.slice(1))),
  live_proposal: null,
  ...overrides,
});

const ROWS: Row[] = [
  row("P003", "Amoxicillin 500 mg capsules", { risk: "high", base_risk: "high", order_qty: 108, available: 60 }),
  row("P011", "Azithromycin 250 mg tablets", {
    risk: "high",
    base_risk: "high",
    order_qty: 30,
    live_proposal: { id: PROPOSAL_ID, status: "awaiting_approval" },
  }),
  row("P001", "Paracetamol 500 mg tablets", { reason_code: "OPEN_PO_UNAVAILABLE", order_qty: null, open_po_qty: null }),
  row("P005", "Metformin 500 mg tablets"),
];

const listBody = (items: Row[]) => ({
  synthetic: true,
  results_exist: true,
  last_end_of_day: "2026-11-18T00:05:03Z",
  items,
});

function ProposalStub() {
  const { id } = useParams();
  return <p>Proposal page {id}</p>;
}

function renderRisk() {
  return render(
    <MemoryRouter initialEntries={["/brain/risk"]}>
      <Routes>
        <Route path="/brain/risk" element={<RiskPage />} />
        <Route path="/brain/proposals/:id" element={<ProposalStub />} />
      </Routes>
    </MemoryRouter>,
  );
}

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

function mockApi(handler: Handler) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url, init) => handler(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const rowOf = (name: string) => screen.getByText(name).closest("tr") as HTMLElement;

describe("Risk and insights: the Action column", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("offers Create proposal only where an order is recommended and nothing is pending", async () => {
    mockApi(() => json(listBody(ROWS)));
    renderRisk();
    await screen.findByText("Amoxicillin 500 mg capsules");
    expect(screen.getAllByRole("columnheader", { name: /action/i }).length).toBeGreaterThan(0);

    expect(within(rowOf("Amoxicillin 500 mg capsules")).getByRole("button", { name: /create proposal/i })).toBeInTheDocument();

    const pending = within(rowOf("Azithromycin 250 mg tablets")).getByRole("link", { name: /proposal pending/i });
    expect(pending).toHaveAttribute("href", `/brain/proposals/${PROPOSAL_ID}`);
    expect(within(rowOf("Azithromycin 250 mg tablets")).queryByRole("button", { name: /create proposal/i })).toBeNull();

    for (const name of ["Paracetamol 500 mg tablets", "Metformin 500 mg tablets"]) {
      expect(within(rowOf(name)).queryByRole("button", { name: /create proposal/i })).toBeNull();
      expect(within(rowOf(name)).queryByRole("link", { name: /proposal pending/i })).toBeNull();
    }
    expect(screen.queryByRole("button", { name: /run|job|poll|train|forecast/i })).not.toBeInTheDocument();
  });

  it("creates a proposal from the row's recommendation and opens it", async () => {
    const fetchMock = mockApi((url, init) => {
      if (url === "/api/v1/brain/proposals" && init?.method === "POST") return json({ id: PROPOSAL_ID }, 201);
      return json(listBody(ROWS));
    });
    renderRisk();
    await screen.findByText("Amoxicillin 500 mg capsules");
    await user().click(within(rowOf("Amoxicillin 500 mg capsules")).getByRole("button", { name: /create proposal/i }));

    expect(await screen.findByText(`Proposal page ${PROPOSAL_ID}`)).toBeInTheDocument();
    const post = fetchMock.mock.calls.find(([, init]) => init?.method === "POST");
    expect(post?.[0]).toBe("/api/v1/brain/proposals");
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ recommendation_id: REC(3) });
  });

  it("explains a changed recommendation and reloads the list", async () => {
    let gets = 0;
    mockApi((_url, init) => {
      if (init?.method === "POST")
        return json(
          { detail: "the recommendation changed; reload to see the new quantity", code: "RECOMMENDATION_CHANGED" },
          409,
        );
      gets += 1;
      return json(listBody(ROWS));
    });
    renderRisk();
    await screen.findByText("Amoxicillin 500 mg capsules");
    await user().click(within(rowOf("Amoxicillin 500 mg capsules")).getByRole("button", { name: /create proposal/i }));
    expect(await screen.findByText(/the recommendation changed; reload to see the new quantity/i)).toBeInTheDocument();
    await waitFor(() => expect(gets).toBeGreaterThanOrEqual(2));
  });
});

// ---------------------------------------------------------------- part 2 (US2)

const SHA = "986ec647450a68348bc4bbf8cda2efb7a593fc9cc2e56367f13452f989fff041";

const proposal = (overrides: Row = {}): Row => ({
  synthetic: true,
  id: PROPOSAL_ID,
  action: "create_purchase_order",
  origin: "recommendation",
  status: "awaiting_approval",
  sending: false,
  supplier_id: "S004",
  supplier_name: "Delta Health Trading",
  arguments: { supplier_id: "S004", lines: [{ product_id: "P003", quantity: 108 }] },
  arguments_sha256: SHA,
  recommendation_id: REC(3),
  purchase_order_id: null,
  created_at: "2026-11-18T09:00:00Z",
  ...overrides,
});

const detail = (overrides: Row = {}): Row => ({
  ...proposal(),
  lines: [{ product_id: "P003", product_name: "Amoxicillin 500 mg capsules", quantity: 108 }],
  recommendation: {
    recommendation_id: REC(3),
    product_id: "P003",
    risk: "high",
    days_of_cover: 2.83,
    lead_time_days: 7,
    order_qty: 108,
    computed_at: "2026-11-18T00:05:00Z",
  },
  newer_recommendation: null,
  approval: null,
  failure: null,
  attempts: [],
  ...overrides,
});

function renderDetail() {
  return render(
    <MemoryRouter initialEntries={["/brain/proposals/" + PROPOSAL_ID]}>
      <Routes>
        <Route path="/brain/proposals/:id" element={<ProposalDetailPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

const isPost = (url: string, init: RequestInit | undefined, suffix: string) =>
  url.endsWith(suffix) && init?.method === "POST";

describe("Proposals list", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("lists proposals with their status, supplier, quantity, origin and ERP order", async () => {
    const items = [
      proposal(),
      proposal({
        id: "a",
        status: "uncertain",
        supplier_id: "S003",
        supplier_name: "Gamma Drug Distribution",
        arguments: { supplier_id: "S003", lines: [{ product_id: "P011", quantity: 30 }] },
      }),
      proposal({ id: "b", status: "draft_created", purchase_order_id: 1001, origin: "assistant", recommendation_id: null }),
      proposal({ id: "c", status: "failed" }),
      proposal({ id: "d", status: "rejected" }),
    ];
    mockApi(() => json({ synthetic: true, items }));
    render(
      <MemoryRouter>
        <ProposalsPage />
      </MemoryRouter>,
    );
    await screen.findAllByText("Delta Health Trading (S004)");
    for (const header of [/created/i, /product/i, /supplier/i, /quantity/i, /origin/i, /status/i, /erp order/i]) {
      expect(screen.getAllByRole("columnheader", { name: header }).length).toBeGreaterThan(0);
    }
    const colors: Record<string, RegExp> = {
      "Awaiting approval": /blue/,
      Uncertain: /orange/,
      "Draft created": /green/,
      Failed: /red/,
    };
    for (const [label, color] of Object.entries(colors)) {
      expect(screen.getByText(label).closest(".ant-tag")?.className).toMatch(color);
    }
    expect(screen.getByText("Rejected").closest(".ant-tag")).toBeTruthy();
    expect(screen.getByText("#1001")).toBeInTheDocument();
    expect(screen.getByText("Assistant")).toBeInTheDocument();
    expect(screen.getByText(/synthetic data/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /run|job|poll|train|forecast/i })).not.toBeInTheDocument();
  });

  it("shows 20 rows a page and an empty state that points to Risk and insights", async () => {
    mockApi(() => json({ synthetic: true, items: Array.from({ length: 25 }, (_, i) => proposal({ id: "p" + i })) }));
    const first = render(
      <MemoryRouter>
        <ProposalsPage />
      </MemoryRouter>,
    );
    await screen.findAllByText("Delta Health Trading (S004)");
    expect(document.querySelectorAll(".ant-table-tbody tr.ant-table-row")).toHaveLength(20);
    first.unmount();
    mockApi(() => json({ synthetic: true, items: [] }));
    render(
      <MemoryRouter>
        <ProposalsPage />
      </MemoryRouter>,
    );
    expect(await screen.findByText(/no proposals yet/i)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /risk and insights/i })).toHaveAttribute("href", "/brain/risk");
  });
});

describe("Proposal detail: approve and reject", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  it("approves with the fingerprint the dialog shows", async () => {
    const fetchMock = mockApi((url, init) => {
      if (isPost(url, init, "/approve"))
        return json(
          detail({
            status: "draft_created",
            purchase_order_id: 1001,
            approval: { approved_by: "manager", approved_at: "2026-11-18T09:01:00Z" },
          }),
        );
      return json(detail());
    });
    renderDetail();
    await user().click(await screen.findByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/Delta Health Trading \(S004\)/)).toBeInTheDocument();
    expect(within(dialog).getByText(/P003/)).toBeInTheDocument();
    expect(within(dialog).getByText(/108 units/)).toBeInTheDocument();
    const shown = within(dialog).getByTestId("approve-fingerprint").textContent?.replace(/\s/g, "");
    expect(shown).toBe(SHA);
    await user().click(within(dialog).getByRole("button", { name: /approve and send/i }));
    await screen.findByText("Draft created");
    const post = fetchMock.mock.calls.find(([u, i]) => isPost(String(u), i, "/approve"));
    expect(JSON.parse(String(post?.[1]?.body))).toEqual({ arguments_sha256: shown });
    expect(screen.getByText("#1001")).toBeInTheDocument();
  });

  it("warns about a newer recommendation on the page and in the dialog", async () => {
    mockApi(() =>
      json(
        detail({
          newer_recommendation: {
            recommendation_id: REC(99),
            product_id: "P003",
            risk: "high",
            days_of_cover: 3.1,
            lead_time_days: 7,
            order_qty: 96,
            computed_at: "2026-11-18T10:07:00Z",
          },
        }),
      ),
    );
    renderDetail();
    expect(await screen.findByText(/a newer recommendation says 96 units/i)).toBeInTheDocument();
    await user().click(screen.getByRole("button", { name: /^approve$/i }));
    const dialog = await screen.findByRole("dialog");
    expect(within(dialog).getByText(/a newer recommendation says 96 units/i)).toBeInTheDocument();
  });

  it("rejects after a confirmation", async () => {
    const fetchMock = mockApi((url, init) => {
      if (isPost(url, init, "/reject")) return json(detail({ status: "rejected" }));
      return json(detail());
    });
    renderDetail();
    await user().click(await screen.findByRole("button", { name: /^reject$/i }));
    await user().click(await screen.findByRole("button", { name: /yes, reject/i }));
    await screen.findByText("Rejected");
    expect(fetchMock.mock.calls.some(([u, i]) => isPost(String(u), i, "/reject"))).toBe(true);
    expect(screen.queryByRole("button", { name: /^approve$/i })).toBeNull();
  });

  it("explains a changed fingerprint", async () => {
    mockApi((url, init) => {
      if (isPost(url, init, "/approve")) return json({ detail: "fingerprint mismatch", code: "FINGERPRINT_MISMATCH" }, 409);
      return json(detail());
    });
    renderDetail();
    await user().click(await screen.findByRole("button", { name: /^approve$/i }));
    await user().click(within(await screen.findByRole("dialog")).getByRole("button", { name: /approve and send/i }));
    expect(await screen.findByText(/the proposal changed; reload it/i)).toBeInTheDocument();
  });

  it("reloads a proposal another tab already handled", async () => {
    let handled = false;
    mockApi((url, init) => {
      if (isPost(url, init, "/approve")) {
        handled = true;
        return json({ detail: "not awaiting approval", code: "NOT_AWAITING_APPROVAL" }, 409);
      }
      return json(handled ? detail({ status: "draft_created", purchase_order_id: 1007 }) : detail());
    });
    renderDetail();
    await user().click(await screen.findByRole("button", { name: /^approve$/i }));
    await user().click(within(await screen.findByRole("dialog")).getByRole("button", { name: /approve and send/i }));
    expect(await screen.findByText(/this proposal was already handled/i)).toBeInTheDocument();
    expect(await screen.findByText("#1007")).toBeInTheDocument();
    expect(screen.getByText("Draft created")).toBeInTheDocument();
  });
});

// ---------------------------------------------------------------- part 3 (US3)

describe("Proposal detail: uncertain and Send again", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => vi.unstubAllGlobals());

  const uncertain = () =>
    detail({
      status: "uncertain",
      approval: { approved_by: "manager", approved_at: "2026-11-18T09:01:00Z" },
      attempts: [
        {
          attempt_no: 1,
          started_at: "2026-11-18T09:01:00Z",
          finished_at: "2026-11-18T09:01:10Z",
          outcome: "uncertain",
          http_status: null,
          erp_code: null,
          detail: "the ERP didn't confirm the draft",
          purchase_order_id: null,
        },
      ],
    });

  it("explains an uncertain send and offers Send again", async () => {
    const fetchMock = mockApi((url, init) => {
      if (isPost(url, init, "/send-again")) return json(detail({ status: "draft_created", purchase_order_id: 1001 }));
      return json(uncertain());
    });
    renderDetail();
    expect(await screen.findByText(/uncertain: the erp didn't confirm the draft/i)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^approve$/i })).toBeNull();
    expect(screen.queryByRole("button", { name: /^reject$/i })).toBeNull();
    await user().click(screen.getByRole("button", { name: /send again/i }));
    await screen.findByText("Draft created");
    expect(fetchMock.mock.calls.some(([u, i]) => isPost(String(u), i, "/send-again"))).toBe(true);
    expect(screen.queryByRole("button", { name: /send again/i })).toBeNull();
  });

  it("shows Sending… with no action while an attempt is in flight", async () => {
    mockApi(() => json({ ...uncertain(), sending: true }));
    renderDetail();
    expect(await screen.findByText("Sending…")).toBeInTheDocument();
    for (const name of [/send again/i, /^approve$/i, /^reject$/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });

  it.each(["draft_created", "failed", "rejected"])("offers no action on a %s proposal", async (status) => {
    mockApi(() =>
      json(
        detail({
          status,
          purchase_order_id: status === "draft_created" ? 1001 : null,
          failure: status === "failed" ? { code: "VALIDATION_ERROR", reason: "the ERP refused the order" } : null,
        }),
      ),
    );
    renderDetail();
    await screen.findByText(/Delta Health Trading \(S004\)/);
    for (const name of [/send again/i, /^approve$/i, /^reject$/i]) {
      expect(screen.queryByRole("button", { name })).toBeNull();
    }
  });
});
