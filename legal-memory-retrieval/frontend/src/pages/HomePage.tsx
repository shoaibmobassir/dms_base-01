import { Link, useNavigate } from "react-router-dom";
import { Action, EmptyState, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { AskComposer } from "@/components/ai/AskComposer";
import { DataTable } from "@/components/common/DataTable";
import { QueryState } from "@/components/common/QueryState";
import { useDeadlines, useHomeStats, useMatters } from "@/api/resources";
import { useApp } from "@/context/AppContext";
import { dueLabel } from "@/pages/CalendarPage";

const EXAMPLES = [
  "What did we argue on maintainability before the Appellate Tribunal for Electricity?",
  "Which matters concern transmission charges under the CERC sharing regulations?",
  "Summarise the PCIJ's approach to reparation in our historical corpus.",
  "Which Security Council resolutions did we advise on in 2025?",
];

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function HomePage() {
  const { me } = useApp();
  const navigate = useNavigate();
  const stats = useHomeStats();
  const openMatters = useMatters({ status: "Open", limit: 6 });
  const deadlines = useDeadlines({ status: "open", limit: 5 });
  const first = me?.name.split(" ")[0];
  const counts = stats.data?.counts;

  const snapshot = counts
    ? [
        { count: counts.matters, text: "matters in your access scope", to: "/matters" },
        { count: counts.documents, text: "documents indexed for retrieval", to: "/documents" },
        { count: counts.open_deadlines, text: "open court deadlines", to: "/calendar" },
        { count: counts.arguments, text: "recorded arguments", to: "/arguments" },
      ]
    : [];

  return (
    <div className="space-y-12">
      <PageHeader
        eyebrow={first ? `${greeting()}, ${first}` : greeting()}
        title="Firm Intelligence"
        subtitle="The firm's knowledge, at work."
        actions={
          <>
            <Action to="/ask" primary icon="forum" testId="home-ask">
              Ask the Firm
            </Action>
            <Action to="/matters" icon="gavel" testId="home-browse">
              Browse Matters
            </Action>
          </>
        }
      />

      <AskComposer examples={EXAMPLES} placeholder="Ask anything about the firm's work…" />

      <section className="grid gap-12 lg:grid-cols-3">
        <div className="space-y-12 lg:col-span-2">
          <div>
            <SectionLabel
              right={
                <Link to="/matters" className="text-xs font-semibold text-wine hover:underline">
                  View all
                </Link>
              }
            >
              Open matters
            </SectionLabel>
            <QueryState
              query={openMatters}
              isEmpty={(d) => d.items.length === 0}
              empty={<EmptyState icon="gavel" title="No open matters in your scope" />}
            >
              {(d) => (
                <DataTable
                  testId="home-matters"
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
                    { key: "client", secondary: true, header: "Client", render: (m) => <span className="text-sm">{m.client_name || "—"}</span> },
                    {
                      key: "status",
                      header: "Status",
                      render: (m) => <StatusLabel status={m.restricted ? "Restricted" : m.status || "Open"} />,
                    },
                  ]}
                />
              )}
            </QueryState>
          </div>

          <div>
            <SectionLabel
              right={
                <Link to="/calendar" className="text-xs font-semibold text-wine hover:underline">
                  All deadlines
                </Link>
              }
            >
              Coming up
            </SectionLabel>
            <QueryState
              query={deadlines}
              isEmpty={(d) => d.length === 0}
              empty={<EmptyState icon="event" title="No open deadlines in your scope" />}
            >
              {(rows) => (
                <ul className="space-y-px" data-testid="home-deadlines">
                  {rows.map((d) => (
                    <li key={d.id}>
                      <Link
                        to={`/matters/${d.matter_id}`}
                        className="flex items-baseline justify-between gap-4 border-b border-border py-3 transition-colors hover:bg-secondary/60"
                      >
                        <span>
                          <span className="block text-foreground">{d.title}</span>
                          <span className="block text-xs text-muted-foreground">
                            {d.matter_code} · {d.court || d.client_name}
                          </span>
                        </span>
                        <span className="shrink-0 font-mono-id text-xs text-wine">{dueLabel(d.due)}</span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </div>
        </div>

        <div>
          <SectionLabel>In your scope</SectionLabel>
          <QueryState query={stats}>
            {() => (
              <div className="space-y-px" data-testid="home-stats">
                {snapshot.map((k) => (
                  <Link
                    key={k.text}
                    to={k.to}
                    className="flex items-baseline gap-3 border-b border-border py-3.5 transition-colors hover:bg-secondary/60"
                  >
                    <span className="font-display text-3xl text-wine">{k.count}</span>
                    <span className="text-sm text-muted-foreground">{k.text}</span>
                  </Link>
                ))}
              </div>
            )}
          </QueryState>
        </div>
      </section>
    </div>
  );
}
