import type { ReactNode } from "react";

import { EmptyState } from "./States";

export interface Column<T> {
  key: string;
  header: ReactNode;
  render: (row: T) => ReactNode;
  align?: "left" | "right";
  className?: string;
}

export function DataTable<T>({
  columns,
  rows,
  rowKey,
  onRowClick,
  empty,
  footer,
}: {
  columns: Column<T>[];
  rows: T[];
  rowKey: (row: T) => string;
  onRowClick?: (row: T) => void;
  empty?: ReactNode;
  footer?: ReactNode;
}) {
  if (rows.length === 0) return <>{empty ?? <EmptyState title="No records" />}</>;
  return (
    <div className="overflow-x-auto">
      <table className={`table ${onRowClick ? "table-hover" : ""}`}>
        <thead>
          <tr>
            {columns.map((c) => (
              <th key={c.key} className={c.align === "right" ? "text-right" : ""}>
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr
              key={rowKey(row)}
              className={onRowClick ? "cursor-pointer" : ""}
              onClick={onRowClick ? () => onRowClick(row) : undefined}
            >
              {columns.map((c) => (
                <td key={c.key} className={`${c.align === "right" ? "num text-right whitespace-nowrap" : ""} ${c.className ?? ""}`}>
                  {c.render(row)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
        {footer}
      </table>
    </div>
  );
}

export function Pager({
  total,
  offset,
  limit,
  onChange,
}: {
  total: number;
  offset: number;
  limit: number;
  onChange: (offset: number) => void;
}) {
  if (total <= limit && offset === 0) {
    return <div className="px-4 py-2 text-xs text-ink-muted">{total} {total === 1 ? "record" : "records"}</div>;
  }
  const end = Math.min(offset + limit, total);
  return (
    <div className="flex items-center justify-between border-t border-line px-4 py-2 text-xs text-ink-muted">
      <span className="num">
        {total === 0 ? 0 : offset + 1}–{end} of {total}
      </span>
      <div className="flex gap-1.5">
        <button type="button" className="btn btn-sm" disabled={offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>
          Previous
        </button>
        <button type="button" className="btn btn-sm" disabled={end >= total} onClick={() => onChange(offset + limit)}>
          Next
        </button>
      </div>
    </div>
  );
}
