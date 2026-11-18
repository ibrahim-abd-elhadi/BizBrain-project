import { type ThemeConfig, theme } from "antd";

// One light theme for every ERP screen (research R-31). Colors and spacing live here, not in pages.
export const PRIMARY = "#0f766e";

export const appTheme: ThemeConfig = {
  algorithm: theme.defaultAlgorithm,
  token: {
    colorPrimary: PRIMARY,
    // Light tints of the primary color, set explicitly: the derived ones come out grey-green.
    colorPrimaryBg: "#e6f4f1",
    colorPrimaryBgHover: "#cfe9e3",
    colorBgLayout: "#f4f6f8",
    borderRadius: 6,
    fontSize: 14,
    // Includes an Arabic face so later Arabic screens render well (README Section 4.6).
    fontFamily:
      '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, "Noto Sans", "Noto Sans Arabic", sans-serif',
  },
  components: {
    Layout: {
      headerBg: "#ffffff",
      headerHeight: 56,
      headerPadding: "0 24px",
      siderBg: "#ffffff",
    },
    Menu: {
      itemSelectedBg: "#e6f4f1",
      itemSelectedColor: PRIMARY,
      itemHoverBg: "#f0f5f4",
    },
    Table: {
      headerBg: "#f7f9fa",
      cellPaddingBlock: 10,
      cellPaddingInline: 12,
    },
  },
};

// Chart colors (feature 003 Forecasts): categorical slots 1 and 2 of the reference data-viz
// palette, checked with its validator on the white card surface (lightness, chroma, colorblind
// separation, contrast: all pass). The forecast is also dashed, so color is never the only cue.
export const CHART = {
  history: "#2a78d6",
  forecast: "#eb6834",
  bandOpacity: 0.18,
  grid: "#e5e7eb",
  axis: "#6b7280",
  today: "#9ca3af",
};
