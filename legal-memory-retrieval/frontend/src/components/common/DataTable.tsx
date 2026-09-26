import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

export type DataTableColumn<T> = {
  key: string;
  header: ReactNode;
  render?: (row: T) => ReactNode;
  align?: "right";
  width?: string | number;
  /** Hidden below the tablet breakpoint to keep phone tables readable. */
  secondary?: boolean;
};

export function DataTable<T extends object = Record<string, unknown>>({
  columns,
  rows,
  onRowClick,
  getRowKey,
  empty,
  testId,
}: {
  columns: DataTableColumn<T>[];
  rows: T[] | null | undefined;
  onRowClick?: (row: T) => void;
  getRowKey?: (row: T) => string | number;
  empty?: ReactNode;
  testId?: string;
}) {
  if (!rows || rows.length === 0) return empty ?? null;
  return (
    <div className="w-full overflow-x-auto" data-testid={testId}>
      <table className="w-full border-collapse text-sm">
        <thead>
          <tr className="border-b border-border">
            {columns.map((c) => (
              <th
                key={c.key}
                className={cn(
                  "meta-label whitespace-nowrap py-3 pr-6 text-left font-semibold",
                  c.align === "right" && "text-right pr-0",
                  c.secondary && "hidden md:table-cell",
                )}
                style={c.width ? { width: c.width } : undefined}
              >
                {c.header}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, i) => {
            const key = getRowKey ? getRowKey(row) : i;
            return (
              <tr
                key={key}
                onClick={onRowClick ? () => onRowClick(row) : undefined}
                className={cn(
                  "border-b border-border transition-colors",
                  onRowClick && "cursor-pointer hover:bg-secondary/60",
                )}
                data-testid={`row-${key}`}
              >
                {columns.map((c) => (
                  <td
                    key={c.key}
                    className={cn(
                      "py-4 pr-6 align-top",
                      c.align === "right" && "text-right pr-0 text-muted-foreground",
                      c.secondary && "hidden md:table-cell",
                    )}
                  >
                    {c.render ? c.render(row) : ((row as Record<string, unknown>)[c.key] as ReactNode)}
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
