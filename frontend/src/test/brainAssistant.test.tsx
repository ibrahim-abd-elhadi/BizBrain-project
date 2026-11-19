// Brain → Assistant (feature 005, US1 and US2; research R-07, R-15). Written first (T025, T034).
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter } from "react-router";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AssistantPage } from "../brain/AssistantPage";
import { json, user } from "./antd";

type Handler = (url: string, init?: RequestInit) => Response | Promise<Response>;

function mockApi(handler: Handler) {
  const fetchMock = vi.fn<(url: string, init?: RequestInit) => Promise<Response>>(async (url, init) => handler(url, init));
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

const AVAILABLE = { synthetic: true, available: true, reason: null };
const OFFLINE = { synthetic: true, available: false, reason: "unreachable" };

const answer = (text: string, language: "en" | "ar" = "en", extra: Record<string, unknown> = {}) => ({
  synthetic: true,
  outcome: "answered",
  offline_reason: null,
  reply: { text, language },
  proposal: null,
  refusal: null,
  cards: [],
  ...extra,
});

const chatBodies = (fetchMock: ReturnType<typeof mockApi>) =>
  fetchMock.mock.calls
    .filter(([url, init]) => url.endsWith("/assistant/messages") && init?.method === "POST")
    .map(([, init]) => JSON.parse(String(init?.body)) as { messages: { role: string; text: string; language?: string }[] });

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/brain/assistant"]}>
      <AssistantPage />
    </MemoryRouter>,
  );
}

async function send(text: string) {
  const box = screen.getByRole("textbox", { name: "Message" });
  fireEvent.change(box, { target: { value: text } });
  await user().click(screen.getByRole("button", { name: /send/i }));
}

const messages = () => screen.getAllByTestId("chat-message");

describe("Assistant (US1)", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
    localStorage.clear();
  });

  it("checks the model when opened and shows Assistant offline with Check again", async () => {
    let available = false;
    const fetchMock = mockApi((url) => (url.includes("/assistant") && !url.includes("/messages") ? json(available ? AVAILABLE : OFFLINE) : json({}, 404)));
    renderPage();
    expect(await screen.findByText("Assistant offline")).toBeInTheDocument();
    expect(screen.getByRole("note")).toHaveTextContent("Synthetic data");
    available = true;
    await user().click(screen.getByRole("button", { name: /check again/i }));
    await waitFor(() => expect(screen.queryByText("Assistant offline")).not.toBeInTheDocument());
    const checks = fetchMock.mock.calls.map(([url]) => url).filter((url) => url.includes("/assistant") && !url.includes("/messages"));
    expect(checks).toEqual(["/api/v1/brain/assistant", "/api/v1/brain/assistant?recheck=true"]);
  });

  it("sends the question, shows Thinking…, then the reply; Enter sends too", async () => {
    let release: (r: Response) => void = () => {};
    mockApi((url) => {
      if (url.endsWith("/assistant")) return json(AVAILABLE);
      return new Promise<Response>((resolve) => {
        release = resolve;
      });
    });
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Which products are at high risk?");
    expect(await screen.findByText("Thinking…")).toBeInTheDocument();
    release(json(answer("P003, P011 and P017 are high.")));
    expect(await screen.findByText("P003, P011 and P017 are high.")).toBeInTheDocument();
    expect(screen.queryByText("Thinking…")).not.toBeInTheDocument();

    const box = screen.getByRole("textbox", { name: "Message" });
    fireEvent.change(box, { target: { value: "And P003?" } });
    fireEvent.keyDown(box, { key: "Enter", code: "Enter" });
    expect(await screen.findByText("And P003?")).toBeInTheDocument();
  });

  it("shows Arabic blocks right to left, and the screen stays English", async () => {
    mockApi((url) =>
      url.endsWith("/assistant") ? json(AVAILABLE) : json(answer("المنتجات ذات الخطر المرتفع: P003", "ar")),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("ما المنتجات ذات الخطر العالي؟");
    await screen.findByText("المنتجات ذات الخطر المرتفع: P003");
    const [question, reply] = messages();
    expect(question).toHaveAttribute("dir", "rtl");
    expect(question).toHaveAttribute("lang", "ar");
    expect(reply).toHaveAttribute("dir", "rtl");
    expect(reply).toHaveAttribute("lang", "ar");
    expect(screen.getByRole("heading", { name: "Assistant" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /send/i })).toHaveTextContent("Send");
  });

  it("an English reply is left to right", async () => {
    mockApi((url) => (url.endsWith("/assistant") ? json(AVAILABLE) : json(answer("P003 is high."))));
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Which products are at high risk?");
    await screen.findByText("P003 is high.");
    for (const block of messages()) expect(block).toHaveAttribute("dir", "ltr");
  });

  it("an offline turn adds Assistant offline and no reply text", async () => {
    mockApi((url) =>
      url.endsWith("/assistant")
        ? json(AVAILABLE)
        : json({ synthetic: true, outcome: "offline", offline_reason: "timeout", reply: null, proposal: null, refusal: null }),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Which products are at high risk?");
    expect(await screen.findAllByText("Assistant offline")).not.toHaveLength(0);
    expect(messages()).toHaveLength(1); // only the manager's question
  });

  it("sends at most the last 20 messages, starting with a manager message, and keeps showing all", async () => {
    let n = 0;
    const fetchMock = mockApi((url) => {
      if (url.endsWith("/assistant")) return json(AVAILABLE);
      n += 1;
      return json(answer(`Answer ${n}`));
    });
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    for (let i = 1; i <= 15; i++) {
      await send(`Question ${i}`);
      await screen.findByText(`Answer ${i}`);
    }
    expect(messages()).toHaveLength(30);
    await send("Question 16");
    await screen.findByText("Answer 16");
    const bodies = chatBodies(fetchMock);
    const first = bodies[0].messages;
    expect(first).toEqual([{ role: "manager", text: "Question 1", language: "en" }]);
    const last = bodies[bodies.length - 1].messages;
    expect(last.length).toBeGreaterThanOrEqual(19);
    expect(last.length).toBeLessThanOrEqual(20);
    expect(last[0].role).toBe("manager");
    expect(last[last.length - 1]).toEqual({ role: "manager", text: "Question 16", language: "en" });
    const assistant = last.find((m) => m.role === "assistant");
    expect(assistant?.language).toBe("en");
  });

  it("keeps nothing after a reload", async () => {
    mockApi((url) => (url.endsWith("/assistant") ? json(AVAILABLE) : json(answer("P003 is high."))));
    const first = renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Which products are at high risk?");
    await screen.findByText("P003 is high.");
    first.unmount();
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    expect(screen.queryAllByTestId("chat-message")).toHaveLength(0);
    expect(localStorage.length).toBe(0);
    expect(Object.keys(sessionStorage)).toEqual(["erp_token"]);
  });
});

describe("Assistant proposal cards (US2)", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  const PROPOSAL = {
    id: "11111111-1111-4111-8111-111111111111",
    path: "/brain/proposals/11111111-1111-4111-8111-111111111111",
    status: "awaiting_approval",
    origin: "assistant",
    supplier_id: "S004",
    supplier_name: "Delta Health Trading",
    lines: [{ product_id: "P003", product_name: "Amoxicillin 500 mg capsules", quantity: 108 }],
  };

  it("shows a card linking to the new proposal, built from the response, with no Approve button", async () => {
    mockApi((url) =>
      url.endsWith("/assistant") ? json(AVAILABLE) : json(answer("Prepared: S004, P003 × 108.", "en", { proposal: PROPOSAL })),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Prepare an order for P003 as recommended");
    const card = await screen.findByTestId("proposal-card");
    expect(card).toHaveTextContent("Proposal created");
    expect(card).toHaveTextContent("Awaiting approval");
    expect(card).toHaveTextContent("Delta Health Trading (S004)");
    expect(card).toHaveTextContent("P003");
    expect(card).toHaveTextContent("108");
    expect(within(card).getByRole("link", { name: /open proposal/i })).toHaveAttribute("href", PROPOSAL.path);
    expect(screen.queryByRole("button", { name: /approve/i })).not.toBeInTheDocument();
  });

  it("shows a pending card for PROPOSAL_PENDING", async () => {
    mockApi((url) =>
      url.endsWith("/assistant")
        ? json(AVAILABLE)
        : json(
            answer("P003 already has a proposal.", "en", {
              refusal: {
                code: "PROPOSAL_PENDING",
                detail: "a proposal for this product is already awaiting approval or uncertain",
                live_proposal_id: PROPOSAL.id,
                path: PROPOSAL.path,
              },
            }),
          ),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Prepare an order for P003");
    const card = await screen.findByTestId("refusal-card");
    expect(card).toHaveTextContent("A proposal is already pending");
    expect(within(card).getByRole("link", { name: /open proposal/i })).toHaveAttribute("href", PROPOSAL.path);
  });

  it("keeps the card when the turn ended offline", async () => {
    mockApi((url) =>
      url.endsWith("/assistant")
        ? json(AVAILABLE)
        : json({ synthetic: true, outcome: "offline", offline_reason: "timeout", reply: null, proposal: PROPOSAL, refusal: null }),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("Prepare an order for P003");
    expect(await screen.findByTestId("proposal-card")).toBeInTheDocument();
    expect(screen.getAllByText("Assistant offline").length).toBeGreaterThan(0);
  });
});

describe("Assistant data cards", () => {
  beforeEach(() => sessionStorage.setItem("erp_token", "test-token"));
  afterEach(() => {
    vi.unstubAllGlobals();
    sessionStorage.clear();
  });

  const SALES_CARD = {
    kind: "sales_summary",
    title: "Sales, all products, 2026-11-12 to 2026-11-18 (7 closed days)",
    first_day: "2026-11-12",
    last_day: "2026-11-18",
    columns: ["Product", "Sold", "Returned", "Net"],
    rows: [
      ["P001 Paracetamol 500 mg tablets", 376, 4, 372],
      ["P016 Vitamin C 1000 mg effervescent tablets", 325, 9, 316],
    ],
    total: ["All products", 3033, 55, 2978],
  };

  it("draws the labeled figures under the reply, even when the text mislabels them", async () => {
    mockApi((url) =>
      url.includes("/assistant") && !url.includes("/messages")
        ? json(AVAILABLE)
        : json(answer("P001 had 376 net units this week.", "en", { cards: [SALES_CARD] })),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("give me a brief for our sales");
    const card = await screen.findByTestId("data-card");
    expect(card).toHaveTextContent("Sales, all products, 2026-11-12 to 2026-11-18");
    const headers = within(card).getAllByRole("columnheader").map((h) => h.textContent);
    expect(headers).toEqual(["Product", "Sold", "Returned", "Net"]);
    const p001 = within(card).getByText("P001 Paracetamol 500 mg tablets").closest("tr") as HTMLElement;
    expect(within(p001).getAllByRole("cell").map((c) => c.textContent)).toEqual([
      "P001 Paracetamol 500 mg tablets",
      "376",
      "4",
      "372",
    ]);
    expect(within(card).getByText("All products").closest("tr")).toHaveTextContent("2978");
  });

  it("keeps the card left to right under an Arabic reply", async () => {
    mockApi((url) =>
      url.includes("/assistant") && !url.includes("/messages")
        ? json(AVAILABLE)
        : json(answer("ملخص المبيعات: P001 صافي 372.", "ar", { cards: [SALES_CARD] })),
    );
    renderPage();
    await screen.findByRole("textbox", { name: "Message" });
    await send("أعطني ملخصًا لمبيعاتنا");
    const card = await screen.findByTestId("data-card");
    expect(card).toHaveAttribute("dir", "ltr");
    expect(within(card).getAllByRole("columnheader").map((h) => h.textContent)).toEqual(["Product", "Sold", "Returned", "Net"]);
  });
});
