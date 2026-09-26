import type { ReactNode } from "react";
import type { UseQueryResult } from "@tanstack/react-query";
import { ApiError } from "@/api/client";
import { EmptyState, ErrorState, TableSkeleton } from "@/components/common/primitives";

/**
 * Renders loading / error / not-found / empty states for a query, then `children`.
 * A 404 is shown as "not found or outside your access scope" — the API returns 404
 * for restricted records so their existence isn't leaked.
 */
export function QueryState<T>({
  query,
  children,
  isEmpty,
  empty,
  notFound,
  loading,
}: {
  query: UseQueryResult<T>;
  children: (data: T) => ReactNode;
  isEmpty?: (data: T) => boolean;
  empty?: ReactNode;
  notFound?: ReactNode;
  loading?: ReactNode;
}) {
  if (query.isPending) return <>{loading ?? <TableSkeleton />}</>;
  if (query.isError) {
    const err = query.error;
    if (err instanceof ApiError && err.status === 404) {
      return (
        <>
          {notFound ?? (
            <EmptyState
              icon="lock"
              title="Not found"
              description="This record does not exist or is outside your access scope."
            />
          )}
        </>
      );
    }
    return (
      <ErrorState
        title="Couldn't load this view"
        description={err instanceof Error ? err.message : "The API did not respond."}
        onRetry={() => void query.refetch()}
      />
    );
  }
  if (isEmpty?.(query.data)) return <>{empty ?? null}</>;
  return <>{children(query.data)}</>;
}

export function Pager({
  page,
  total,
  pageSize,
  onPage,
}: {
  page: number;
  total: number;
  pageSize: number;
  onPage: (page: number) => void;
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (pages <= 1) return null;
  const from = page * pageSize + 1;
  const to = Math.min(total, (page + 1) * pageSize);
  return (
    <div className="flex items-center justify-between pt-2 text-sm text-muted-foreground" data-testid="pager">
      <span>
        {from}–{to} of {total}
      </span>
      <div className="flex gap-2">
        <button
          type="button"
          disabled={page === 0}
          onClick={() => onPage(page - 1)}
          className="rounded-md border border-border px-3 py-1.5 font-medium text-foreground transition-colors hover:bg-secondary disabled:opacity-40"
        >
          Previous
        </button>
        <button
          type="button"
          disabled={page >= pages - 1}
          onClick={() => onPage(page + 1)}
          className="rounded-md border border-border px-3 py-1.5 font-medium text-foreground transition-colors hover:bg-secondary disabled:opacity-40"
        >
          Next
        </button>
      </div>
    </div>
  );
}
