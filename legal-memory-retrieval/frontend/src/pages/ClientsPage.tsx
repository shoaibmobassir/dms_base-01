import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { PAGE_SIZE, useClients } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { can, useMyAccess } from "@/api/access";
import { ConflictQueue, NewClientDialog } from "@/components/clients/ClientIntake";
import { Pager, QueryState } from "@/components/common/QueryState";
import { useDebounced } from "@/lib/use-debounced";

export function ClientsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const q = useDebounced(query.trim());
  const clients = useClients({ q, page });
  const myAccess = useMyAccess();
  const [creating, setCreating] = useState(false);

  useEffect(() => setPage(0), [q]);

  return (
    <div className="space-y-8">
      <PageHeader
        compact
        title="Clients"
        count={clients.data ? `${clients.data.total} ${clients.data.total === 1 ? "client" : "clients"}` : undefined}
        subtitle="Open a client to see their matters and what the firm has learned working with them."
        actions={
          can(myAccess.data, "clients.create") ? (
            <Action primary icon="add" onClick={() => setCreating(true)} testId="clients-new">
              New client
            </Action>
          ) : undefined
        }
      />
      {can(myAccess.data, "conflicts.decide") && <ConflictQueue />}
      {creating && <NewClientDialog open onClose={() => setCreating(false)} />}
      <SearchField value={query} onChange={setQuery} placeholder="Search by name or industry…" testId="clients-search" />
      <QueryState query={clients} isEmpty={(d) => d.items.length === 0} empty={<EmptyState title="No clients found" />}>
        {(d) => (
          <>
            <DataTable
              testId="clients-table"
              getRowKey={(c) => c.client_id}
              getRowHref={(c) => `/clients/${c.client_id}`}
              onRowClick={(c) => navigate(`/clients/${c.client_id}`)}
              rows={d.items}
              columns={[
                {
                  key: "name",
                  header: "Client",
                  render: (c) => (
                    <div>
                      <MonoId>{c.client_id}</MonoId>
                      <div className="text-foreground">
                        {c.name}
                        {c.status && c.status !== "active" && (
                          <span className="ml-2 rounded bg-warning-soft px-1.5 text-xs text-warning-ink" data-testid="client-status">{c.status.replace(/_/g, " ")}</span>
                        )}
                      </div>
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
