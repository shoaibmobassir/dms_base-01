import type { ReactNode } from "react";

/** The bar that appears while rows are selected: how many, the actions, and a way to clear. */
export function BulkBar({ count, noun, onClear, children }: { count: number; noun: string; onClear: () => void; children: ReactNode }) {
  if (count === 0) return null;
  return (
    <div
      className="sticky top-0 z-20 flex flex-wrap items-center gap-2 rounded-md border border-wine/30 bg-wine-soft px-3 py-2 text-sm"
      role="region"
      aria-label="Selected rows"
      data-testid="bulk-bar"
    >
      <span className="font-medium text-wine" data-testid="bulk-count">
        {count} {noun}{count === 1 ? "" : "s"} selected
      </span>
      <div className="flex flex-wrap items-center gap-1.5">{children}</div>
      <button type="button" onClick={onClear} className="ml-auto text-xs font-medium text-wine hover:underline" data-testid="bulk-clear">
        Clear selection
      </button>
    </div>
  );
}
