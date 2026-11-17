import { UploadOutlined } from "@ant-design/icons";
import { Alert, Button, Card, Space, Table, Tag, Typography, Upload } from "antd";
import { useState } from "react";
import { apiFetch } from "../../api/client";
import type { UploadResult } from "../../api/types";
import { messageOf } from "../../api/useApiData";
import { ErrorAlert } from "../../components/ErrorAlert";

interface Props {
  /** Called after an upload so the sales table can refresh. */
  onDone: () => void;
}

// Replaces today's totals from a CSV file (FR-013, FR-014, FR-026). Valid rows are recorded even
// when others are refused; whole-file problems come back as one message.
export function UploadPanel({ onDone }: Props) {
  const [file, setFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<UploadResult | null>(null);

  async function submit() {
    if (file === null) return;
    setBusy(true);
    setError(null);
    try {
      const form = new FormData();
      form.append("file", file);
      // FormData: no JSON Content-Type, so the browser adds the multipart boundary itself.
      const outcome = await apiFetch<UploadResult>("/sales/upload", { method: "POST", body: form });
      setResult(outcome);
      onDone();
    } catch (caught) {
      setResult(null);
      setError(messageOf(caught));
    } finally {
      setBusy(false);
    }
  }

  const refusedCount = result?.refused.length ?? 0;

  return (
    <section aria-label="Upload CSV" className="panel-card">
      <Card title="Upload CSV" className="panel-card">
        <Typography.Paragraph type="secondary">
          Columns: business_date, product_id, units_sold, units_returned. Only today&apos;s date is
          accepted, and each row replaces that product&apos;s total for today.
        </Typography.Paragraph>
        <Space wrap align="start">
          <Upload
            accept=".csv"
            maxCount={1}
            beforeUpload={(chosen) => {
              setFile(chosen);
              return false; // keep the file here; it is sent only when Upload is pressed
            }}
            onRemove={() => setFile(null)}
            fileList={file ? [{ uid: "chosen", name: file.name, status: "done" }] : []}
          >
            <Button icon={<UploadOutlined aria-hidden />}>Choose CSV file</Button>
          </Upload>
          <Button type="primary" disabled={file === null} loading={busy} onClick={() => void submit()}>
            Upload
          </Button>
        </Space>

        {(error || result) && (
          <div className="panel-result" aria-live="polite">
            <ErrorAlert error={error} />
            {result && (
              <>
                <Alert
                  type={refusedCount > 0 ? "warning" : "success"}
                  showIcon
                  title={`Accepted: ${result.accepted.length} · Refused: ${refusedCount} · Overridden: ${result.overridden.length}`}
                />
                {refusedCount > 0 && (
                  <Table
                    size="small"
                    rowKey="row"
                    title={() => "Refused rows"}
                    dataSource={result.refused}
                    pagination={refusedCount > 5 ? { pageSize: 5, showSizeChanger: false } : false}
                    columns={[
                      { title: "Row", dataIndex: "row", width: 64 },
                      {
                        title: "Code",
                        dataIndex: "code",
                        render: (code: string) => <Tag color="red">{code}</Tag>,
                      },
                      { title: "Detail", dataIndex: "detail" },
                    ]}
                  />
                )}
                {result.overridden.length > 0 && (
                  <Alert
                    type="info"
                    showIcon
                    title="Overridden rows (the last row for a product and date wins)"
                    description={
                      <ul>
                        {result.overridden.map((o) => (
                          <li key={o.row}>{`row ${o.row} overridden by row ${o.overridden_by_row}`}</li>
                        ))}
                      </ul>
                    }
                  />
                )}
              </>
            )}
          </div>
        )}
      </Card>
    </section>
  );
}
