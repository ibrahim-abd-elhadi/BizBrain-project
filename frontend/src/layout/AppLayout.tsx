import {
  AlertOutlined,
  AuditOutlined,
  DatabaseOutlined,
  FileTextOutlined,
  FundOutlined,
  LineChartOutlined,
  LogoutOutlined,
  MedicineBoxOutlined,
  ShopOutlined,
  UserOutlined,
} from "@ant-design/icons";
import { Button, Layout, Menu, Space, Tag, Typography } from "antd";
import { useEffect, useState } from "react";
import { Link, Outlet, useLocation, useNavigate } from "react-router";
import { apiFetch, isSignedIn, logout } from "../api/client";
import "./app.css";

const LINKS = [
  { to: "/products", label: "Products", icon: <MedicineBoxOutlined aria-hidden /> },
  { to: "/suppliers", label: "Suppliers", icon: <ShopOutlined aria-hidden /> },
  { to: "/inventory", label: "Inventory", icon: <DatabaseOutlined aria-hidden /> },
  { to: "/sales", label: "Sales", icon: <LineChartOutlined aria-hidden /> },
  { to: "/purchase-orders", label: "Purchase orders", icon: <FileTextOutlined aria-hidden /> },
];

/** The Brain's read-only screens (feature 003). */
const BRAIN_LINKS = [
  { to: "/brain/risk", label: "Risk and insights", icon: <AlertOutlined aria-hidden /> },
  { to: "/brain/forecasts", label: "Forecasts", icon: <FundOutlined aria-hidden /> },
  { to: "/brain/proposals", label: "Proposals", icon: <AuditOutlined aria-hidden /> },
];

const menuItem = (link: (typeof LINKS)[number]) => ({
  key: link.to,
  icon: link.icon,
  label: <Link to={link.to}>{link.label}</Link>,
});

/** The signed-in manager's username, from the existing GET /auth/me. */
function useCurrentUser(signedIn: boolean): string | null {
  const [username, setUsername] = useState<string | null>(null);
  useEffect(() => {
    if (!signedIn) return;
    let cancelled = false;
    apiFetch<{ username: string }>("/auth/me")
      .then((me) => {
        if (!cancelled) setUsername(me.username);
      })
      .catch(() => {
        // A 401 already sends the manager to /login (api/client.ts); nothing else to show.
      });
    return () => {
      cancelled = true;
    };
  }, [signedIn]);
  return signedIn ? username : null;
}

/** Wraps every route, login included, so the "Synthetic data" tag is on every screen (FR-027). */
export function AppLayout() {
  const navigate = useNavigate();
  const { pathname } = useLocation(); // re-renders on navigation, so the shell follows sign-in
  const signedIn = isSignedIn();
  const username = useCurrentUser(signedIn);
  const current = [...LINKS, ...BRAIN_LINKS].find((link) => pathname.startsWith(link.to))?.to;

  function signOut() {
    logout();
    navigate("/login");
  }

  return (
    <Layout className="app">
      <Layout.Header className="app-header">
        <div className="brand">
          <span className="brand-mark" aria-hidden>
            B
          </span>
          <Typography.Text strong className="brand-name">
            BizBrain ERP
          </Typography.Text>
        </div>
        <Tag color="gold" role="note" data-testid="synthetic-banner" className="synthetic-tag">
          Synthetic data
        </Tag>
        <div className="header-spacer" />
        {signedIn && (
          <Space size="middle">
            <span className="header-user">
              <UserOutlined aria-hidden />
              <span data-testid="signed-in-user">{username ?? "…"}</span>
            </span>
            <Button icon={<LogoutOutlined aria-hidden />} onClick={signOut}>
              Sign out
            </Button>
          </Space>
        )}
      </Layout.Header>
      <Layout>
        {signedIn && (
          <Layout.Sider width={220} theme="light" className="app-sider">
            <nav aria-label="Main">
              <Menu
                mode="inline"
                selectedKeys={current ? [current] : []}
                items={[
                  {
                    type: "group",
                    key: "erp",
                    label: "ERP",
                    children: LINKS.map(menuItem),
                  },
                  {
                    type: "group",
                    key: "brain",
                    label: "Brain",
                    children: BRAIN_LINKS.map(menuItem),
                  },
                ]}
              />
            </nav>
          </Layout.Sider>
        )}
        <Layout.Content className="app-content">
          <Outlet />
        </Layout.Content>
      </Layout>
    </Layout>
  );
}
