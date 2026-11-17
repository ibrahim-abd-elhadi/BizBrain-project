import { App as AntApp, ConfigProvider } from "antd";
import type { ReactNode } from "react";
import { appTheme } from "./theme";

export type Direction = "ltr" | "rtl";

/** The page's text direction, from <html dir>. Left to right unless a page sets dir="rtl". */
export function documentDirection(): Direction {
  return typeof document !== "undefined" && document.documentElement.dir === "rtl" ? "rtl" : "ltr";
}

interface Props {
  children: ReactNode;
  /** Defaults to <html dir>, so an Arabic screen can switch to right to left without code changes. */
  direction?: Direction;
}

/** The app root: the light theme and Ant Design's right-to-left support (research R-31). */
export function AppProviders({ children, direction = documentDirection() }: Props) {
  return (
    <ConfigProvider theme={appTheme} direction={direction}>
      <AntApp>{children}</AntApp>
    </ConfigProvider>
  );
}
