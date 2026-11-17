import type { TablePaginationConfig } from "antd";

/** Every ERP table shows 20 rows per page. */
export const PAGE_SIZE = 20;

export const pagination: TablePaginationConfig = {
  pageSize: PAGE_SIZE,
  showSizeChanger: false,
  showTotal: (total) => `${total} rows`,
};

/** Sorters for table columns. */
export const byText =
  <T>(pick: (row: T) => string) =>
  (a: T, b: T) =>
    pick(a).localeCompare(pick(b));

export const byNumber =
  <T>(pick: (row: T) => number) =>
  (a: T, b: T) =>
    pick(a) - pick(b);
