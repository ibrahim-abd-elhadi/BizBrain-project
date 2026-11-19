import { Alert, Button, Card, Empty, Input, Space, Table, Tag, Typography } from "antd";
import { useCallback, useEffect, useRef, useState } from "react";
import { Link } from "react-router";
import { BRAIN_BASE, apiFetch } from "../api/client";
import type {
  Availability,
  CardCell,
  ChatMessage,
  ChatProposal,
  ChatRefusal,
  ChatReply,
  DataCard,
  Language,
} from "../api/brainTypes";
import { messageOf } from "../api/useApiData";
import { PageHeader } from "../components/PageHeader";
import { detectLanguage, textDirection } from "./language";
import { SyntheticTag } from "./shared";

/** One entry of the open conversation. Held in React state only: never stored (FR-021). */
type Entry =
  | {
      kind: "message";
      role: "manager" | "assistant";
      text: string;
      language: Language;
      proposal?: ChatProposal | null;
      refusal?: ChatRefusal | null;
      cards?: DataCard[];
    }
  | { kind: "offline"; proposal?: ChatProposal | null; refusal?: ChatRefusal | null; cards?: DataCard[] }
  | { kind: "error"; text: string };

const MAX_MESSAGES = 20;

/** The messages sent with a turn: at most the last 20, starting with a manager message (U1).
 * The screen keeps showing the whole conversation; older turns drop out of what the model sees. */
export function lastTurnMessages(entries: Entry[]): ChatMessage[] {
  const all: ChatMessage[] = entries.flatMap((e) =>
    e.kind === "message" ? [{ role: e.role, text: e.text, language: e.language }] : [],
  );
  let recent = all.slice(-MAX_MESSAGES);
  while (recent.length > 0 && recent[0].role !== "manager") recent = recent.slice(1);
  return recent;
}

function ProposalCard({ proposal }: { proposal: ChatProposal }) {
  return (
    <Card size="small" className="chat-card" data-testid="proposal-card">
      <Space orientation="vertical" size={4}>
        <Space wrap>
          <Typography.Text strong>Proposal created</Typography.Text>
          <Tag color="blue">Awaiting approval</Tag>
        </Space>
        <span>
          Supplier: {proposal.supplier_name} ({proposal.supplier_id})
        </span>
        {proposal.lines.map((line) => (
          <span key={line.product_id}>
            {line.product_id} {line.product_name} × {line.quantity}
          </span>
        ))}
        <Link to={proposal.path}>Open proposal</Link>
        <Typography.Text type="secondary" className="small-note">
          Review, approve or reject it on the Proposals screen. Nothing is sent to the ERP before you approve.
        </Typography.Text>
      </Space>
    </Card>
  );
}

function RefusalCard({ refusal }: { refusal: ChatRefusal }) {
  const pending = refusal.code === "PROPOSAL_PENDING";
  return (
    <Card size="small" className="chat-card" data-testid="refusal-card">
      <Space orientation="vertical" size={4}>
        <Typography.Text strong>{pending ? "A proposal is already pending" : "No proposal was created"}</Typography.Text>
        {!pending && <span>{refusal.detail}</span>}
        {refusal.path && <Link to={refusal.path}>Open proposal</Link>}
      </Space>
    </Card>
  );
}

/** Labeled figures built by code from the tool results: the reply's numbers with their labels. */
function DataCardTable({ card }: { card: DataCard }) {
  const rows = [...card.rows, ...(card.total ? [card.total] : [])].map((cells, n) => ({
    key: n,
    total: card.total !== null && n === card.rows.length,
    cells,
  }));
  const columns = card.columns.map((label, i) => ({
    title: label,
    key: label,
    align: (i === 0 ? "start" : "end") as "start" | "end",
    render: (_: unknown, row: { cells: CardCell[]; total: boolean }) => {
      const value = row.cells[i] ?? "—";
      return row.total ? <Typography.Text strong>{value}</Typography.Text> : value;
    },
  }));
  return (
    <Card size="small" className="chat-card data-card" data-testid="data-card" dir="ltr" title={card.title}>
      <Table size="small" pagination={false} columns={columns} dataSource={rows} rowKey="key" />
    </Card>
  );
}

function Cards({
  proposal,
  refusal,
  cards,
}: {
  proposal?: ChatProposal | null;
  refusal?: ChatRefusal | null;
  cards?: DataCard[];
}) {
  return (
    <>
      {(cards ?? []).map((card, n) => (
        <DataCardTable key={n} card={card} />
      ))}
      {proposal && <ProposalCard proposal={proposal} />}
      {refusal && <RefusalCard refusal={refusal} />}
    </>
  );
}

/** Brain → Assistant: chat with the assistant in English or Arabic (feature 005, US1 and US2).
 * Arabic text is shown right to left inside the English screen (FR-001a). */
export function AssistantPage() {
  const [entries, setEntries] = useState<Entry[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [checking, setChecking] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const check = useCallback(async (recheck = false) => {
    setChecking(true);
    try {
      setAvailability(await apiFetch<Availability>(recheck ? "/assistant?recheck=true" : "/assistant", {}, BRAIN_BASE));
    } catch {
      setAvailability({ synthetic: true, available: false, reason: "unreachable" });
    } finally {
      setChecking(false);
    }
  }, []);

  useEffect(() => {
    void check();
  }, [check]);

  useEffect(() => {
    bottom.current?.scrollIntoView?.({ block: "end" });
  }, [entries, thinking]);

  const previousLanguage = (): Language | null => {
    for (let i = entries.length - 1; i >= 0; i--) {
      const e = entries[i];
      if (e.kind === "message" && e.role === "assistant") return e.language;
    }
    return null;
  };

  async function send() {
    const text = draft.trim();
    if (!text || thinking) return;
    const question: Entry = { kind: "message", role: "manager", text, language: detectLanguage(text, previousLanguage()) };
    const next = [...entries, question];
    setEntries(next);
    setDraft("");
    setThinking(true);
    try {
      const reply = await apiFetch<ChatReply>(
        "/assistant/messages",
        { method: "POST", body: { messages: lastTurnMessages(next) } },
        BRAIN_BASE,
      );
      if (reply.outcome === "offline" || reply.reply === null) {
        setEntries((current) => [
          ...current,
          { kind: "offline", proposal: reply.proposal, refusal: reply.refusal, cards: reply.cards },
        ]);
        setAvailability({ synthetic: true, available: false, reason: reply.offline_reason ?? "unreachable" });
      } else {
        setEntries((current) => [
          ...current,
          {
            kind: "message",
            role: "assistant",
            text: reply.reply!.text,
            language: reply.reply!.language,
            proposal: reply.proposal,
            refusal: reply.refusal,
            cards: reply.cards,
          },
        ]);
        setAvailability({ synthetic: true, available: true, reason: null });
      }
    } catch (caught) {
      setEntries((current) => [...current, { kind: "error", text: messageOf(caught) }]);
    } finally {
      setThinking(false);
    }
  }

  const offline = availability !== null && !availability.available;

  return (
    <div className="page">
      <PageHeader
        title="Assistant"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>
              Ask about sales, forecasts, stock, risk and open orders, in English or Arabic, or ask for a
              purchase-order proposal. Every number comes from the Brain or the ERP.
            </span>
          </Space>
        }
      />
      {offline && (
        <Alert
          type="warning"
          showIcon
          title="Assistant offline"
          description="The language model can't be reached right now. Forecasts, risk, recommendations and proposals still work."
          action={
            <Button size="small" loading={checking} onClick={() => void check(true)}>
              Check again
            </Button>
          }
        />
      )}
      <Card className="chat-card-list">
        {entries.length === 0 && !thinking ? (
          <Empty description="No messages yet. The conversation isn't saved: reloading starts a new one." />
        ) : (
          <div className="chat-list">
            {entries.map((entry, n) => {
              if (entry.kind === "message") {
                const direction = textDirection(entry.language);
                return (
                  <div key={n} className={`chat-entry chat-${entry.role}`}>
                    <div data-testid="chat-message" data-role={entry.role} className="chat-bubble" {...direction}>
                      {entry.text}
                    </div>
                    <Cards proposal={entry.proposal} refusal={entry.refusal} cards={entry.cards} />
                  </div>
                );
              }
              if (entry.kind === "offline")
                return (
                  <div key={n} className="chat-entry chat-assistant">
                    <Alert type="warning" showIcon title="Assistant offline" className="chat-note" />
                    <Cards proposal={entry.proposal} refusal={entry.refusal} cards={entry.cards} />
                  </div>
                );
              return (
                <div key={n} className="chat-entry chat-assistant">
                  <Alert type="error" showIcon title={entry.text} className="chat-note" />
                </div>
              );
            })}
            {thinking && (
              <div className="chat-entry chat-assistant">
                <Typography.Text type="secondary">Thinking…</Typography.Text>
              </div>
            )}
            <div ref={bottom} />
          </div>
        )}
      </Card>
      <Card>
        <Space.Compact className="chat-input">
          <Input.TextArea
            aria-label="Message"
            value={draft}
            autoSize={{ minRows: 1, maxRows: 6 }}
            maxLength={2000}
            placeholder="Ask a question, in English or Arabic"
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                void send();
              }
            }}
          />
          <Button type="primary" onClick={() => void send()} loading={thinking} disabled={!draft.trim()}>
            Send
          </Button>
        </Space.Compact>
      </Card>
    </div>
  );
}
