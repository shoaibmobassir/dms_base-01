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
  selection,
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
  /** Adds a checkbox column. Needs `getRowKey`. */
  selection?: { selected: ReadonlySet<string | number>; onChange: (next: Set<string | number>) => void; label: (row: T) => string };
  empty?: ReactNode;
  testId?: string;
}) {
  if (!rows || rows.length === 0) return empty ?? null;
  const onPage = selection && getRowKey ? rows.filter((r) => selection.selected.has(getRowKey(r))).length : 0;
  const allOnPage = onPage > 0 && onPage === rows.length;
  const someOnPage = onPage > 0;
  return (
    <div className="w-full overflow-x-auto" data-testid={testId}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            {selection && getRowKey && (
              <th className="w-10 py-3 pr-2 text-left">
                <input
                  type="checkbox"
                  aria-label="Select all rows on this page"
                  data-testid="select-all"
                  checked={allOnPage}
                  ref={(el) => {
                    if (el) el.indeterminate = someOnPage && !allOnPage;
                  }}
                  onChange={() => {
                    const next = new Set(selection.selected);
                    for (const r of rows) (allOnPage ? next.delete(getRowKey(r)) : next.add(getRowKey(r)));
                    selection.onChange(next);
                  }}
                  className="h-4 w-4 accent-[var(--wine)]"
                />
              </th>
            )}
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
                {selection && getRowKey && (
                  <td className="w-10 py-4 pr-2 align-top" onClick={(e) => e.stopPropagation()}>
                    <input
                      type="checkbox"
                      aria-label={`Select ${selection.label(row)}`}
                      data-testid={`select-${key}`}
                      checked={selection.selected.has(key)}
                      onChange={() => {
                        const next = new Set(selection.selected);
                        if (next.has(key)) next.delete(key);
                        else next.add(key);
                        selection.onChange(next);
                      }}
                      className="h-4 w-4 accent-[var(--wine)]"
                    />
                  </td>
                )}
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
