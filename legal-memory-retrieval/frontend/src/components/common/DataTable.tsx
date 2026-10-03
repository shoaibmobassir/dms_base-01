import type { KeyboardEvent, ReactNode } from "react";
import { Link } from "react-router-dom";
import { cn } from "@/lib/utils";

export type DataTableColumn<T> = {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  align?: "right";
  width?: string | number;
  /** Hidden below the tablet breakpoint to keep phone tables readable. */
  secondary?: boolean;
  /** The name the server sorts this column by; the header becomes a sort button. */
  sortKey?: string;
};

export type TableSort = { key: string; dir: "asc" | "desc" };

export function DataTable<T extends object = Record<string, unknown>>({
  columns,
  rows,
  onRowClick,
  getRowKey,
  getRowHref,
  sort,
  onSort,
  empty,
  testId,
}: {
  columns: DataTableColumn<T>[];
  rows: T[] | null | undefined;
  onRowClick?: (row: T) => void;
  getRowKey?: (row: T) => string | number;
  /** Where the row leads. The first cell becomes a real link (open in a new tab, copy link). */
  getRowHref?: (row: T) => string;
  /** The current sort, and what to do when a sortable header is pressed. */
  sort?: TableSort;
  onSort?: (sort: TableSort) => void;
  empty?: ReactNode;
  testId?: string;
}) {
  if (!rows || rows.length === 0) return empty ?? null;
  return (
    <div className="w-full overflow-x-auto" data-testid={testId}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            {columns.map((c, ci) => (
              <th
                key={c.key}
                className={cn(
                  "meta-label whitespace-nowrap py-3 pr-6 text-left font-semibold",
                  // Only the last column sits flush with the table edge.
                  c.align === "right" && "text-right",
                  ci === columns.length - 1 && "pr-0",
                  c.secondary && "hidden md:table-cell",
                )}
                style={c.width ? { width: c.width } : undefined}
                aria-sort={c.sortKey && sort?.key === c.sortKey ? (sort?.dir === "asc" ? "ascending" : "descending") : undefined}
              >
                {c.sortKey && onSort ? (
                  <button
                    type="button"
                    onClick={() => onSort({ key: c.sortKey!, dir: sort?.key === c.sortKey && sort?.dir === "asc" ? "desc" : "asc" })}
                    className={cn("inline-flex items-center gap-1 hover:text-foreground", sort?.key === c.sortKey && "text-foreground")}
                    data-testid={`sort-${c.sortKey}`}
                  >
                    {c.header}
                    <span className="material-symbols-outlined" style={{ fontSize: 14 }} aria-hidden="true">
                      {sort?.key === c.sortKey ? (sort?.dir === "asc" ? "arrow_upward" : "arrow_downward") : "unfold_more"}
                    </span>
                  </button>
                ) : (
                  c.header
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = getRowKey ? getRowKey(row) : i;
            const href = getRowHref?.(row);
            const onKeyDown = onRowClick
              ? (e: KeyboardEvent<HTMLTableRowElement>) => {
                  // Only when the row itself has focus: links and buttons inside keep their own keys.
                  if (e.target === e.currentTarget && (e.key === "Enter" || e.key === " ")) {
                    e.preventDefault();
                    onRowClick(row);
                  }
                }
              : undefined;
            return (
              <tr
                key={key}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                onKeyDown={onKeyDown}
                tabIndex={onRowClick ? 0 : undefined}
                className={cn(
                  "border-b border-border transition-colors",
                  onRowClick && "cursor-pointer hover:bg-secondary/60 focus-visible:bg-secondary/60 focus-visible:outline-offset-[-2px]",
                )}
                data-testid={`row-${key}`}
              >
                {columns.map((c, ci) => (
                  <td
                    key={c.key}
                    className={cn(
                      "py-4 pr-6 align-top",
                      c.align === "right" && "text-right text-muted-foreground",
                      ci === columns.length - 1 && "pr-0",
                      c.secondary && "hidden md:table-cell",
                    )}
                  >
                    {(() => {
                      const content = c.render ? c.render(row) : ((row as Record<string, unknown>)[c.key] as ReactNode);
                      return href && ci === 0 ? (
                        <Link to={href} onClick={(e) => e.stopPropagation()} className="block hover:text-wine focus-visible:text-wine">
                          {content}
                        </Link>
                      ) : (
                        content
                      );
                    })()}
                  </td>
                ))}
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
