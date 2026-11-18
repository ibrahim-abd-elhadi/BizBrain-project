import { Alert, Button, Card, Descriptions, Modal, Popconfirm, Space, Table, Timeline, Typography } from "antd";
import { useState } from "react";
import { Link, useParams } from "react-router";
import type { ProposalAttempt, ProposalDetail, RecommendationSummary } from "../api/brainTypes";
import { ApiError, BRAIN_BASE, apiFetch } from "../api/client";
import { messageOf, useApiData } from "../api/useApiData";
import { ErrorAlert } from "../components/ErrorAlert";
import { PageHeader } from "../components/PageHeader";
import {
  ORIGIN_LABELS,
  ProposalStatusTag,
  RiskTag,
  SyntheticTag,
  cairoTime,
  days,
  groupedFingerprint,
} from "./shared";

const newerText = (n: RecommendationSummary) =>
  `A newer recommendation says ${n.order_qty ?? 0} units (computed at ${cairoTime(n.computed_at)}).`;

const OUTCOME_TEXT: Record<NonNullable<ProposalAttempt["outcome"]>, string> = {
  draft_created: "draft created",
  uncertain: "uncertain",
  failed: "failed",
  not_sent: "not sent",
};

function attemptText(a: ProposalAttempt): string {
  if (a.outcome === null) return `Attempt ${a.attempt_no}: sending…`;
  const http = a.http_status !== null ? ` (HTTP ${a.http_status})` : "";
  if (a.outcome === "draft_created" && a.purchase_order_id !== null)
    return `Attempt ${a.attempt_no}: draft created, ERP order #${a.purchase_order_id}${http}`;
  return `Attempt ${a.attempt_no}: ${OUTCOME_TEXT[a.outcome]}${http}${a.detail ? `, ${a.detail}` : ""}`;
}

/** What went wrong with an action, in words the manager can act on (FR-013, FR-020). */
function actionMessage(caught: unknown): string {
  if (caught instanceof ApiError) {
    if (caught.code === "FINGERPRINT_MISMATCH") return "The proposal changed; reload it and check it again.";
    if (caught.code === "NOT_AWAITING_APPROVAL" || caught.code === "NOT_UNCERTAIN")
      return "This proposal was already handled; showing its current state.";
  }
  return messageOf(caught);
}

/** Brain → Proposals → one proposal: review, approve or reject it (feature 004, research R-12). */
export function ProposalDetailPage() {
  const { id = "" } = useParams();
  const loaded = useApiData<ProposalDetail>(`/proposals/${id}`, BRAIN_BASE);
  const [updated, setUpdated] = useState<ProposalDetail | null>(null);
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const p = updated ?? loaded.data;

  async function act(path: string, body?: Record<string, string>) {
    setBusy(true);
    setNotice(null);
    try {
      const result = await apiFetch<ProposalDetail>(`/proposals/${id}/${path}`, { method: "POST", body }, BRAIN_BASE);
      setUpdated(result);
    } catch (caught) {
      setNotice(actionMessage(caught));
      setUpdated(null);
      loaded.reload();
    } finally {
      setBusy(false);
      setConfirming(false);
    }
  }

  if (!p) {
    return (
      <div className="page">
        <PageHeader title="Proposal" />
        <ErrorAlert error={loaded.error} />
      </div>
    );
  }

  const total = p.lines.reduce((sum, line) => sum + line.quantity, 0);
  const awaiting = p.status === "awaiting_approval" && !p.sending;
  const uncertain = p.status === "uncertain" && !p.sending;
  const lastAttempt = p.attempts.length ? p.attempts[p.attempts.length - 1] : null;
  const supplier = `${p.supplier_name ?? "Unknown supplier"} (${p.supplier_id})`;

  return (
    <div className="page">
      <PageHeader
        title="Proposal"
        subtitle={
          <Space size={8} wrap>
            <SyntheticTag />
            <span>A purchase order the Brain proposes. Nothing reaches the ERP until you approve it.</span>
          </Space>
        }
        actions={
          (uncertain && (
            <Button type="primary" loading={busy} onClick={() => void act("send-again")}>
              Send again
            </Button>
          )) ||
          (awaiting && (
            <>
              <Popconfirm
                title="Reject this proposal? It can't be undone."
                okText="Yes, reject"
                cancelText="Keep it"
                onConfirm={() => void act("reject")}
              >
                <Button disabled={busy}>Reject</Button>
              </Popconfirm>
              <Button type="primary" loading={busy} onClick={() => setConfirming(true)}>
                Approve
              </Button>
            </>
          ))
        }
      />
      <ErrorAlert error={loaded.error} />
      {notice && <Alert type="warning" showIcon title={notice} />}
      <Space orientation="vertical" size={16} style={{ inlineSize: "100%" }}>
        {p.newer_recommendation && <Alert type="warning" showIcon title={newerText(p.newer_recommendation)} />}
        {uncertain && (
          <Alert
            type="warning"
            showIcon
            title={`Uncertain: ${lastAttempt?.detail ?? "the ERP didn't confirm the draft"}`}
            description={
              (lastAttempt ? `Last attempt at ${cairoTime(lastAttempt.started_at)}. ` : "") +
              "Send again repeats the exact same request, so the ERP can never create a second order."
            }
          />
        )}
        {p.status === "failed" && p.failure && (
          <Alert type="error" showIcon title={`Failed: ${p.failure.reason}`} description="Create a new proposal to try again." />
        )}
        <Card>
          <Descriptions
            size="small"
            column={{ xs: 1, md: 2 }}
            items={[
              { key: "status", label: "Status", children: <ProposalStatusTag status={p.status} sending={p.sending} /> },
              { key: "supplier", label: "Supplier", children: supplier },
              { key: "origin", label: "Origin", children: ORIGIN_LABELS[p.origin] },
              { key: "created", label: "Created", children: cairoTime(p.created_at) },
              ...(p.approval
                ? [
                    {
                      key: "approved",
                      label: "Approved",
                      children: `by ${p.approval.approved_by} at ${cairoTime(p.approval.approved_at)}`,
                    },
                  ]
                : []),
              ...(p.purchase_order_id !== null
                ? [{ key: "order", label: "ERP order", children: `#${p.purchase_order_id}` }]
                : []),
              {
                key: "fingerprint",
                label: "Fingerprint",
                span: 2,
                children: (
                  <Typography.Text code copyable={{ text: p.arguments_sha256 }} className="fingerprint">
                    {groupedFingerprint(p.arguments_sha256)}
                  </Typography.Text>
                ),
              },
            ]}
          />
        </Card>
        <Card title="Lines">
          <Table
            rowKey="product_id"
            size="small"
            pagination={false}
            dataSource={p.lines}
            columns={[
              { title: "Product", dataIndex: "product_id", width: 100 },
              { title: "Name", dataIndex: "product_name" },
              { title: "Quantity", dataIndex: "quantity", align: "end" },
            ]}
          />
        </Card>
        {p.recommendation && (
          <Card title="From the recommendation">
            <Descriptions
              size="small"
              column={{ xs: 1, md: 3 }}
              items={[
                { key: "risk", label: "Risk", children: <RiskTag level={p.recommendation.risk} /> },
                {
                  key: "cover",
                  label: "Days of cover",
                  children:
                    p.recommendation.days_of_cover === null ? "unlimited" : p.recommendation.days_of_cover.toFixed(2),
                },
                {
                  key: "lead",
                  label: "Lead time",
                  children: p.recommendation.lead_time_days === null ? "—" : days(p.recommendation.lead_time_days),
                },
                { key: "qty", label: "Recommended quantity", children: p.recommendation.order_qty ?? "—" },
                { key: "at", label: "Computed at", children: cairoTime(p.recommendation.computed_at) },
              ]}
            />
          </Card>
        )}
        <Card title="History">
          <Timeline
            items={[
              { key: "created", content: `Created ${cairoTime(p.created_at)}` },
              ...(p.approval
                ? [{ key: "approved", content: `Approved by ${p.approval.approved_by} at ${cairoTime(p.approval.approved_at)}` }]
                : []),
              ...p.attempts.map((a) => ({ key: `attempt-${a.attempt_no}`, content: attemptText(a) })),
            ]}
          />
        </Card>
        <Link to="/brain/proposals">All proposals</Link>
      </Space>
      <Modal
        open={confirming}
        title="Approve and send this proposal?"
        okText="Approve and send"
        cancelText="Cancel"
        confirmLoading={busy}
        onOk={() => void act("approve", { arguments_sha256: p.arguments_sha256 })}
        onCancel={() => setConfirming(false)}
        destroyOnHidden
      >
        <Space orientation="vertical" size={8} style={{ inlineSize: "100%" }}>
          <Typography.Text>Supplier: {supplier}</Typography.Text>
          {p.lines.map((line) => (
            <Typography.Text key={line.product_id}>
              {line.product_id} · {line.product_name ?? "Unknown product"} × {line.quantity}
            </Typography.Text>
          ))}
          <Typography.Text strong>{total} units in total</Typography.Text>
          <Typography.Text type="secondary">Fingerprint you are approving:</Typography.Text>
          <Typography.Text code data-testid="approve-fingerprint" className="fingerprint">
            {groupedFingerprint(p.arguments_sha256)}
          </Typography.Text>
          {p.newer_recommendation && <Alert type="warning" showIcon title={newerText(p.newer_recommendation)} />}
          <Typography.Text type="secondary">
            The Brain sends this exact order to the ERP as a draft; you confirm it there.
          </Typography.Text>
        </Space>
      </Modal>
    </div>
  );
}
