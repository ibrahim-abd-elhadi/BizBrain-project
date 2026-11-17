import { Alert } from "antd";

/** Shows the API's `detail` (or a connection message). Renders nothing when there is no error. */
export function ErrorAlert({ error }: { error: string | null | undefined }) {
  if (!error) return null;
  return <Alert type="error" showIcon title={error} />;
}
