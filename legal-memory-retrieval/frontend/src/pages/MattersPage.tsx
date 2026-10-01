import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataTable } from "@/components/common/DataTable";
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
  const [status, setStatus] = useState("All");
  const [page, setPage] = useState(0);
  const q = useDebounced(query.trim());
  const matters = useMatters({ q, status: status === "All" ? undefined : status, page });
  const myAccess = useMyAccess();
  const [creating, setCreating] = useState(false);

  useEffect(() => setPage(0), [q, status]);

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
      {creating && (
        <NewMatterDialog open onClose={() => setCreating(false)} onCreated={(id) => { setCreating(false); navigate(`/matters/${id}`); }} />
      )}

      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchField value={query} onChange={setQuery} placeholder="Search by title, code or client…" testId="matters-search" />
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
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
              onRowClick={(m) => navigate(`/matters/${m.matter_id}`)}
              rows={d.items}
              columns={[
                {
                  key: "matter",
                  header: "Matter",
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
                  render: (m) => <StatusLabel status={m.restricted ? "Restricted" : m.status || "Open"} />,
                },
                { key: "docs", secondary: true, header: "Documents", align: "right", render: (m) => <span className="text-sm tabular-nums">{m.document_count ?? "—"}</span> },
                { key: "opened", secondary: true, header: "Opened", align: "right", render: (m) => <span className="whitespace-nowrap text-sm tabular-nums">{formatDate(m.opened_date)}</span> },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
