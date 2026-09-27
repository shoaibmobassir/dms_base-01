import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PAGE_SIZE, useClients } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { EmptyState, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { useDebounced } from "@/lib/use-debounced";

export function ClientsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const q = useDebounced(query.trim());
  const clients = useClients({ q, page });

  useEffect(() => setPage(0), [q]);

  return (
    <div className="space-y-8">
      <PageHeader
        compact
        title="Clients"
        count={clients.data ? `${clients.data.total} ${clients.data.total === 1 ? "client" : "clients"}` : undefined}
        subtitle="Open a client to see their matters and what the firm has learned working with them."
      />
      <SearchField value={query} onChange={setQuery} placeholder="Search by name or industry…" testId="clients-search" />
      <QueryState query={clients} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="No clients found" />}>
        {(d) => (
          <>
            <DataTable
              testId="clients-table"
              getRowKey={(c) => c.client_id}
              onRowClick={(c) => navigate(`/clients/${c.client_id}`)}
              rows={d.items}
              columns={[
                {
                  key: "name",
                  header: "Client",
                  render: (c) => (
                    <div>
                      <MonoId>{c.client_id}</MonoId>
                      <div className="text-foreground">{c.name}</div>
                    </div>
                  ),
                },
                { key: "industry", header: "Industry", render: (c) => <span className="text-sm text-muted-foreground">{c.industry || "—"}</span> },
                {
                  key: "matters",
                  header: "Open matters",
                  align: "right",
                  render: (c) => (
                    <span className="text-sm tabular-nums" title={`${c.total_matters ?? 0} matters in total that you can access`}>
                      {c.open_matters ?? 0}
                      <span className="text-muted-foreground"> / {c.total_matters ?? 0}</span>
                    </span>
                  ),
                },
                {
                  key: "lead",
                  secondary: true,
                  header: "Relationship lead",
                  render: (c) => (
                    <span className="text-sm" title="Leads the most of this client's matters">
                      {c.relationship_lead || "—"}
                    </span>
                  ),
                },
                { key: "hq", secondary: true, header: "Headquarters", align: "right", render: (c) => c.headquarters || "—" },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
    </div>
  );
}
