import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { DataTable, type TableSort } from "@/components/common/DataTable";
import { Action, EmptyState, PageHeader, SearchField, StatusLabel } from "@/components/common/primitives";
import { can, useMyAccess } from "@/api/access";
import { NewMatterDialog } from "@/components/matter/MatterEditors";
import { Pager, QueryState } from "@/components/common/QueryState";
import { PAGE_SIZE, useMatters } from "@/api/resources";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

const PILLS = ["All", "Open", "Closed"];

export function MattersPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  // Status, "my matters" and the sort live in the URL: they survive a reload and can be shared.
  const [params, setParams] = useSearchParams();
  const status = params.get("status") ?? "All";
  const mine = params.get("mine") === "1";
  const sort: TableSort | undefined = params.get("sort")
    ? { key: params.get("sort")!, dir: params.get("dir") === "asc" ? "asc" : "desc" }
    : undefined;
  const update = (patch: Record<string, string | null>) =>
    setParams(
      (prev) => {
        const next = new URLSearchParams(prev);
        for (const [k, v] of Object.entries(patch)) {
          if (v === null) next.delete(k);
          else next.set(k, v);
        }
        return next;
      },
      { replace: true },
    );
  const setStatus = (v: string) => update({ status: v === "All" ? null : v });
  const q = useDebounced(query.trim());
  const matters = useMatters({ q, status: status === "All" ? undefined : status, mine, sort, page });
  const myAccess = useMyAccess();
  // "New matter" in the command palette arrives as ?new=1.
  const [creating, setCreating] = useState(params.get("new") === "1");
  useEffect(() => {
    if (params.get("new") === "1")
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("new");
        return next;
      }, { replace: true });
  }, [params, setParams]);

  useEffect(() => setPage(0), [q, status, mine, params.get("sort"), params.get("dir")]);

  return (
    <div className="space-y-8">
      <PageHeader
        compact
        title="Matters"
        count={matters.data ? `${matters.data.total} ${matters.data.total === 1 ? "matter" : "matters"}` : undefined}
        subtitle="Every matter you can access, newest first."
        actions={
          can(myAccess.data, "matters.create") ? (
            <Action primary icon="add" onClick={() => setCreating(true)} testId="matters-new">
              New matter
            </Action>
          ) : undefined
        }
      />
      {creating && can(myAccess.data, "matters.create") && (
        <NewMatterDialog open onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); navigate(`/matters/${id}`); }} />
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchField value={query} onChange={setQuery} placeholder="Search by title, code or client…" testId="matters-search" />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <button
            type="button"
            onClick={() => update({ mine: mine ? null : "1" })}
            aria-pressed={mine}
            data-testid="matters-mine"
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              mine ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary",
            )}
          >
            My matters
          </button>
          {PILLS.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStatus(s)}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                status === s ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary",
              )}
            >
              {s}
            </button>
          ))}
        </div>
      </div>

      <QueryState
        query={matters}
        isEmpty={(d) => d.items.length === 0}
        empty={
          <EmptyState
            title="No matters found"
            description="No matters match your search within your current access scope."
            tips={["Try a broader search term", "Clear the status filter", "Use firm-wide search (⌘K)"]}
          />
        }
      >
        {(d) => (
          <>
            <DataTable
              testId="matters-table"
              getRowKey={(m) => m.matter_id}
              getRowHref={(m) => `/matters/${m.matter_id}`}
              onRowClick={(m) => navigate(`/matters/${m.matter_id}`)}
              rows={d.items}
              sort={sort}
              onSort={(next) => update({ sort: next.key, dir: next.dir })}
              columns={[
                {
                  key: "matter",
                  header: "Matter",
                  sortKey: "title",
                  render: (m) => (
                    <div>
                      <div className="font-mono-id text-xs text-muted-foreground">{m.matter_code}</div>
                      <div className="text-foreground">{m.title}</div>
                    </div>
                  ),
                },
                {
                  key: "client",
                  header: "Client",
                  sortKey: "client",
                  render: (m) => (
                    <div className="text-sm">
                      <div>{m.client_name || "—"}</div>
                      <div className="text-xs text-muted-foreground">{m.practice_area}</div>
                    </div>
                  ),
                },
                { key: "lead", secondary: true, header: "Lead", render: (m) => <span className="text-sm">{m.lead_name || "—"}</span> },
                {
                  key: "next",
                  secondary: true,
                  header: "Next deadline",
                  sortKey: "deadline",
                  render: (m) =>
                    m.next_deadline_date ? (
                      <div className="text-sm" title={m.next_deadline_title ?? undefined}>
                        <div className="tabular-nums">{formatDate(m.next_deadline_date)}</div>
                        <div className="max-w-[200px] truncate text-xs text-muted-foreground">{m.next_deadline_title}</div>
                      </div>
                    ) : (
                      <span className="text-sm text-muted-foreground">—</span>
                    ),
                },
                {
                  key: "status",
                  header: "Status",
                  sortKey: "status",
                  render: (m) => <StatusLabel status={m.restricted ? "Restricted" : m.status || "Open"} />,
                },
                { key: "docs", secondary: true, header: "Documents", sortKey: "documents", align: "right", render: (m) => <span className="text-sm tabular-nums">{m.document_count ?? "—"}</span> },
                { key: "opened", secondary: true, header: "Opened", sortKey: "opened", align: "right", render: (m) => <span className="whitespace-nowrap text-sm tabular-nums">{formatDate(m.opened_date)}</span> },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
