import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { DataTable } from "@/components/common/DataTable";
import { EmptyState, PageHeader, SearchField, StatusLabel } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { PAGE_SIZE, useMatters } from "@/api/resources";
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

  useEffect(() => setPage(0), [q, status]);

  return (
    <div className="space-y-8">
      <PageHeader eyebrow="Matters" title="All institutional knowledge begins with the matter." />

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
                { key: "client", header: "Client", render: (m) => <span className="text-sm">{m.client_name || "—"}</span> },
                { key: "practice", secondary: true, header: "Practice", render: (m) => <span className="text-sm text-muted-foreground">{m.practice_area}</span> },
                {
                  key: "status",
                  header: "Status",
                  render: (m) => <StatusLabel status={m.restricted ? "Restricted" : m.status || "Open"} />,
                },
                { key: "opened", secondary: true, header: "Opened", align: "right", render: (m) => <span className="text-sm">{m.opened_date || "—"}</span> },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
