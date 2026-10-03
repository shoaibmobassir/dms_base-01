import { Link, useNavigate } from "react-router-dom";
import { Action, EmptyState, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { AskComposer } from "@/components/ai/AskComposer";
import { DataTable } from "@/components/common/DataTable";
import { QueryState } from "@/components/common/QueryState";
import { useQuery } from "@tanstack/react-query";
import { listAskHistory, useQuestionIdeas } from "@/api/ask";
import { useDeadlines, useHomeStats, useMatters, useRecentConversations } from "@/api/resources";
import { dueLabel, formatDate } from "@/lib/format";
import { useApp } from "@/context/AppContext";
import { MyWork } from "@/components/home/MyWork";

function greeting() {
  const h = new Date().getHours();
  if (h < 12) return "Good morning";
  if (h < 18) return "Good afternoon";
  return "Good evening";
}

export function HomePage() {
  const { me, identityKey } = useApp();
  const navigate = useNavigate();
  const ideas = useQuestionIdeas(3);
  const stats = useHomeStats();
  const openMatters = useMatters({ status: "Open", limit: 6 });
  const deadlines = useDeadlines({ status: "open", limit: 6 });
  const recent = useRecentConversations();
  const questions = useQuery({ queryKey: [identityKey, "ask-history"], queryFn: () => listAskHistory(), enabled: !!identityKey });
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
        actions={
          <>
            <Action to="/chat" icon="edit_note" testId="home-assistant">
              New Assistant conversation
            </Action>
            <Action to="/matters" icon="gavel" testId="home-browse">
              Browse matters
            </Action>
          </>
        }
      />

      <AskComposer examples={ideas} placeholder="Ask anything about the firm's work…" />

      {counts && counts.matters === 0 && (
        <EmptyState
          icon="gavel"
          title="No matters in your access scope yet"
          description="Open a matter to start filing documents, tracking court dates and asking the firm about its work."
          action={
            <Action to="/matters?new=1" primary icon="add" testId="home-new-matter">
              New matter
            </Action>
          }
        />
      )}

      <MyWork />

      <section className="grid gap-12 lg:grid-cols-3">
        <div className="space-y-12 lg:col-span-2">
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
                        <span className="min-w-0">
                          <span className="block text-foreground">
                            {d.title}
                            {d.owner_member_id && d.owner_member_id === me?.member_id && (
                              <span className="ml-2 rounded bg-wine-soft px-1.5 py-px align-middle text-xs font-semibold uppercase text-wine">Yours</span>
                            )}
                          </span>
                          <span className="block truncate text-xs text-muted-foreground">
                            {d.matter_title} · {d.court || d.client_name}
                          </span>
                        </span>
                        <span className="shrink-0 text-right">
                          <span className="block text-xs tabular-nums text-foreground">{formatDate(d.due)}</span>
                          <span className="block text-xs text-wine">{dueLabel(d.due)}</span>
                        </span>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </QueryState>
          </div>
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

        </div>

        <div className="space-y-12">
          <RecentList
            label="Your recent questions"
            testId="home-recent-questions"
            more={{ to: "/ask", text: "Ask the Firm" }}
            empty="Questions you ask the firm appear here."
            items={(questions.data?.items ?? []).slice(0, 4).map((h) => ({
              key: h.id,
              to: `/ask?${new URLSearchParams({ q: h.query, ...(h.scope ? { scope: h.scope, scopeType: h.scope_type ?? "auto" } : {}) })}`,
              title: h.query,
              meta: [formatDate(h.asked_at), h.scope].filter(Boolean).join(" · "),
            }))}
          />
          <RecentList
            label="Your recent conversations"
            testId="home-recent-conversations"
            more={{ to: "/chat?history=open", text: "All conversations" }}
            empty="Assistant conversations appear here."
            items={(recent.data ?? []).slice(0, 4).map((c) => ({
              key: c.id,
              to: `/chat/${c.id}`,
              title: c.title || "Untitled conversation",
              meta: formatDate(c.updated_at),
            }))}
          />
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
        </div>
      </section>
    </div>
  );
}

function RecentList({
  label,
  items,
  more,
  empty,
  testId,
}: {
  label: string;
  items: { key: string; to: string; title: string; meta: string }[];
  more: { to: string; text: string };
  empty: string;
  testId: string;
}) {
  return (
    <div data-testid={testId}>
      <SectionLabel
        right={
          <Link to={more.to} className="text-xs font-semibold text-wine hover:underline">
            {more.text}
          </Link>
        }
      >
        {label}
      </SectionLabel>
      {items.length === 0 ? (
        <p className="text-sm text-muted-foreground">{empty}</p>
      ) : (
        <ul className="space-y-px">
          {items.map((it) => (
            <li key={it.key}>
              <Link to={it.to} className="block border-b border-border py-2.5 transition-colors hover:bg-secondary/60">
                <span className="line-clamp-2 text-sm text-foreground">{it.title}</span>
                <span className="block text-xs text-muted-foreground">{it.meta}</span>
              </Link>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
