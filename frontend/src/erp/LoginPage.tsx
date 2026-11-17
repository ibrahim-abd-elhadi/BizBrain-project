import { Button, Card, Form, Input, Typography } from "antd";
import { useState } from "react";
import { useNavigate } from "react-router";
import { ApiError, login } from "../api/client";
import { ErrorAlert } from "../components/ErrorAlert";

interface Credentials {
  username: string;
  password: string;
}

export function LoginPage() {
  const navigate = useNavigate();
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function onFinish({ username, password }: Credentials) {
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      navigate("/products");
    } catch (caught) {
      setError(caught instanceof ApiError ? caught.detail : "Could not reach the server");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login-page">
      <Card className="login-card">
        <Typography.Title level={1}>Sign in</Typography.Title>
        <Typography.Paragraph type="secondary">Pharmacy manager account</Typography.Paragraph>
        <Form<Credentials>
          name="sign-in"
          layout="vertical"
          requiredMark={false}
          onFinish={(values) => void onFinish(values)}
          aria-label="Sign in"
        >
          <Form.Item
            label="Username"
            name="username"
            rules={[{ required: true, message: "Enter your username" }]}
          >
            <Input autoComplete="username" autoFocus />
          </Form.Item>
          <Form.Item
            label="Password"
            name="password"
            rules={[{ required: true, message: "Enter your password" }]}
          >
            <Input.Password autoComplete="current-password" />
          </Form.Item>
          {error && (
            <div className="form-error">
              <ErrorAlert error={error} />
            </div>
          )}
          <Button type="primary" htmlType="submit" block loading={busy}>
            Sign in
          </Button>
        </Form>
      </Card>
    </div>
  );
}
