import { Space, Typography } from "antd";
import type { ReactNode } from "react";

interface Props {
  title: string;
  subtitle?: ReactNode;
  /** Buttons shown on the right, for example "Add product". */
  actions?: ReactNode;
}

/** The title row every screen starts with. */
export function PageHeader({ title, subtitle, actions }: Props) {
  return (
    <div className="page-header">
      <div>
        <Typography.Title level={1} className="page-title">
          {title}
        </Typography.Title>
        {subtitle && (
          <Typography.Text type="secondary" className="page-subtitle">
            {subtitle}
          </Typography.Text>
        )}
      </div>
      {actions && <Space wrap>{actions}</Space>}
    </div>
  );
}
