import { useNavigate, useParams } from "react-router-dom";
import { useClient } from "@/api/resources";
import type { ClientNote } from "@/api/types";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, MonoId, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";

const NOTE_GROUPS: { kind: ClientNote["kind"]; label: string }[] = [
  { kind: "prefers", label: "Prefers" },
  { kind: "avoid", label: "Avoid" },
  { kind: "terms", label: "Commercial terms" },
];

export function ClientDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const client = useClient(id);

  return (
    <QueryState query={client} loading={<p className="text-sm text-muted-foreground">Loading client…</p>}>
      {(c) => (
        <div className="space-y-10">
          <PageHeader
            eyebrow="Client memory"
            title={c.name}
            subtitle="What the firm has observed working with this client — each note traceable to the matter it came from."
            actions={
              <Action to={`/ask?scope=${encodeURIComponent(c.name)}&scopeType=client`} primary icon="forum">
                Ask about this client
              </Action>
            }
          >
            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
              <MonoId className="text-sm">{c.client_id}</MonoId>
              {c.industry && <span>{c.industry}</span>}
              {c.headquarters && <span>{c.headquarters}</span>}
            </div>
          </PageHeader>

          <section>
            <SectionLabel>Observed preferences</SectionLabel>
            {c.notes.length === 0 ? (
              <EmptyState icon="psychology" title="Nothing recorded yet" description="No client notes are visible within your access scope." />
            ) : (
              <div className="grid gap-6 md:grid-cols-3" data-testid="client-notes">
                {NOTE_GROUPS.map((g) => {
                  const notes = c.notes.filter((n) => n.kind === g.kind);
                  if (notes.length === 0) return null;
                  return (
                    <div key={g.kind}>
                      <div className="meta-label mb-2">{g.label}</div>
                      <ul className="space-y-3">
                        {notes.map((n) => (
                          <li key={n.note_id} className="text-sm leading-relaxed">
                            {n.text}
                            <div className="mt-0.5 text-xs text-muted-foreground">
                              {[n.author_name, n.source_matter_code].filter(Boolean).join(" · ")}
                            </div>
                          </li>
                        ))}
                      </ul>
                    </div>
                  );
                })}
              </div>
            )}
          </section>

          <section>
            <SectionLabel>Matters in your scope</SectionLabel>
            <DataTable
              testId="client-matters"
              getRowKey={(m) => m.matter_id}
              onRowClick={(m) => navigate(`/matters/${m.matter_id}`)}
              rows={c.matters}
              empty={<EmptyState title="No matters for this client in your scope" />}
              columns={[
                {
                  key: "matter",
                  header: "Matter",
                  render: (m) => (
                    <div>
                      <div className="font-mono-id text-xs text-muted-foreground">{m.matter_code}</div>
                      <div>{m.title}</div>
                    </div>
                  ),
                },
                { key: "practice", header: "Practice", render: (m) => m.practice_area },
                { key: "opened", header: "Opened", render: (m) => m.opened_date || "—" },
                { key: "status", header: "Status", align: "right", render: (m) => <StatusLabel status={m.status || "Open"} /> },
              ]}
            />
          </section>
        </div>
      )}
    </QueryState>
  );
}
