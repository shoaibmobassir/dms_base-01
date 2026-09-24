import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  setPinned,
  usePinnedMatters,
  useDeadlines,
  useDocuments,
  useMatter,
  useMatterArguments,
  useMatterRelated,
  useMatterTimeline,
} from "@/api/resources";
import type { MatterDetail } from "@/api/types";
import { DataTable } from "@/components/common/DataTable";
import { ClientLink, PersonAvatar } from "@/components/common/EntityLink";
import { Action, EmptyState, Icon, MonoId, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { initials, useApp } from "@/context/AppContext";
import { dueLabel } from "@/pages/CalendarPage";
import { cn } from "@/lib/utils";

const TABS = ["Overview", "Documents", "Timeline", "Deadlines", "People", "Arguments", "Related"] as const;
type Tab = (typeof TABS)[number];

export function MatterDetailPage() {
  const { id = "" } = useParams();
  const matter = useMatter(id);

  return (
    <QueryState query={matter} loading={<p className="text-sm text-muted-foreground">Loading matter…</p>}>
      {(detail) => <MatterView key={detail.matter.matter_id} detail={detail} />}
    </QueryState>
  );
}

function PinAction({ matterId }: { matterId: string }) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const pinned = usePinnedMatters();
  const isPinned = (pinned.data ?? []).some((p) => p.matter_id === matterId);
  const [busy, setBusy] = useState(false);
  const toggle = async () => {
    setBusy(true);
    try {
      await setPinned(matterId, !isPinned);
      await queryClient.invalidateQueries({ queryKey: [identityKey, "pinned-matters"] });
    } catch (err) {
      toast(err instanceof Error ? err.message : "Could not update pin");
    } finally {
      setBusy(false);
    }
  };
  return (
    <Action onClick={busy ? undefined : () => void toggle()} icon="push_pin" testId="matter-pin">
      {isPinned ? "Unpin" : "Pin"}
    </Action>
  );
}

function MatterView({ detail }: { detail: MatterDetail }) {
  const { matter: m, team } = detail;
  const [tab, setTab] = useState<Tab>("Overview");

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Matter"
        title={m.title}
        subtitle={m.client_name ? <ClientLink id={m.client_id} name={m.client_name} /> : undefined}
        actions={
          <>
            <Action to={`/ask?scope=${encodeURIComponent(m.matter_code)}`} primary icon="forum" testId="matter-ask">
              Ask about this matter
            </Action>
            <PinAction matterId={m.matter_id} />
          </>
        }
      >
        <div className="mt-4 flex flex-wrap items-center gap-4">
          <MonoId className="text-sm">{m.matter_code}</MonoId>
          <StatusLabel status={m.status || "Open"} />
          {m.restricted && <StatusLabel status="Restricted" />}
          <span className="text-sm text-muted-foreground">
            {[m.practice_area, m.court || m.jurisdiction].filter(Boolean).join(" · ")}
          </span>
        </div>
      </PageHeader>

      <div className="sticky top-0 z-10 -mx-6 border-b border-border bg-background/90 px-6 backdrop-blur lg:-mx-10 lg:px-10">
        <div className="flex gap-1 overflow-x-auto" role="tablist">
          {TABS.map((t) => (
            <button
              key={t}
              type="button"
              role="tab"
              aria-selected={tab === t}
              onClick={() => setTab(t)}
              data-testid={`matter-tab-${t.toLowerCase()}`}
              className={cn(
                "relative whitespace-nowrap px-3 py-3 text-sm font-medium transition-colors",
                tab === t ? "text-wine" : "text-muted-foreground hover:text-foreground",
              )}
            >
              {t}
              {tab === t && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-wine" />}
            </button>
          ))}
        </div>
      </div>

      <div className="animate-fade">
        {tab === "Overview" && <Overview detail={detail} />}
        {tab === "Documents" && <DocumentsTab matterId={m.matter_id} />}
        {tab === "Timeline" && <TimelineTab matterId={m.matter_id} />}
        {tab === "Deadlines" && <DeadlinesTab matterId={m.matter_id} />}
        {tab === "People" &&
          (team.length === 0 ? (
            <EmptyState icon="groups" title="No team recorded" />
          ) : (
            <div className="grid gap-3 sm:grid-cols-2">
              {team.map((tm) => (
                <Link
                  key={tm.member_id}
                  to={`/people/${tm.member_id}`}
                  className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 transition-colors hover:border-wine/40"
                >
                  <PersonAvatar person={{ name: tm.name, initials: initials(tm.name) }} size={40} />
                  <div>
                    <div className="font-medium text-foreground">{tm.name}</div>
                    <div className="text-xs text-muted-foreground">
                      {tm.role_on_matter} · {tm.role}
                    </div>
                  </div>
                </Link>
              ))}
            </div>
          ))}
        {tab === "Arguments" && <ArgumentsTab matterId={m.matter_id} />}
        {tab === "Related" && <RelatedTab matterId={m.matter_id} />}
      </div>
    </div>
  );
}

function Overview({ detail }: { detail: MatterDetail }) {
  const { matter: m, team } = detail;
  return (
    <div className="grid gap-6 lg:grid-cols-3">
      <div className="space-y-6 lg:col-span-2">
        <div className="rounded-lg border border-border bg-card p-6">
          <SectionLabel>Facts</SectionLabel>
          {m.facts.length === 0 ? (
            <p className="text-sm text-muted-foreground">No facts recorded for this matter.</p>
          ) : (
            <ul className="space-y-2 text-[15px] leading-relaxed text-foreground">
              {m.facts.map((f) => (
                <li key={f}>{f}</li>
              ))}
            </ul>
          )}
        </div>
        {m.legal_issues.length > 0 && (
          <div className="rounded-lg border border-border bg-card p-6">
            <SectionLabel>Legal issues</SectionLabel>
            <div className="flex flex-wrap gap-1.5">
              {m.legal_issues.map((k) => (
                <span key={k} className="rounded-full bg-secondary px-2.5 py-0.5 text-xs">
                  {k}
                </span>
              ))}
            </div>
          </div>
        )}
      </div>
      <div className="space-y-6">
        <div className="rounded-lg border border-border bg-card p-5">
          <SectionLabel>Parties</SectionLabel>
          <dl className="space-y-2.5 text-sm">
            <Field label="Client">{m.client_name}</Field>
            <Field label="Opposing party">{m.opposing_party}</Field>
            <Field label="Forum">{m.court}</Field>
            <Field label="Jurisdiction">{m.jurisdiction}</Field>
            <Field label="Opened">{m.opened_date}</Field>
            {m.closed_date && <Field label="Closed">{m.closed_date}</Field>}
            {m.outcome && <Field label="Outcome">{m.outcome}</Field>}
          </dl>
        </div>
        <div className="rounded-lg border border-border bg-card p-5">
          <SectionLabel>Team</SectionLabel>
          <div className="space-y-2.5">
            {team.length === 0 && <p className="text-sm text-muted-foreground">No team recorded.</p>}
            {team.map((tm) => (
              <div key={tm.member_id} className="flex items-center justify-between text-sm">
                <Link to={`/people/${tm.member_id}`} className="hover:text-wine">
                  {tm.name}
                </Link>
                <span className="text-xs text-muted-foreground">{tm.role_on_matter}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-muted-foreground">{label}</dt>
      <dd>{children || "—"}</dd>
    </div>
  );
}

function DocumentsTab({ matterId }: { matterId: string }) {
  const navigate = useNavigate();
  const docs = useDocuments({ matter_id: matterId, limit: 200 });
  return (
    <QueryState query={docs} isEmpty={(d) => d.items.length === 0} empty={<EmptyState icon="description" title="No documents on this matter" />}>
      {(d) => (
        <DataTable
          testId="matter-documents"
          getRowKey={(doc) => doc.document_id}
          onRowClick={(doc) => navigate(`/documents/${doc.document_id}`)}
          rows={d.items}
          columns={[
            {
              key: "name",
              header: "Name",
              render: (doc) => (
                <span className="flex items-center gap-2">
                  <Icon name="description" className="text-muted-foreground" style={{ fontSize: 16 }} />
                  {doc.title}
                </span>
              ),
            },
            { key: "type", header: "Type", render: (doc) => <span className="text-sm text-muted-foreground">{doc.document_type}</span> },
            { key: "author", header: "Author", render: (doc) => <span className="text-sm text-muted-foreground">{doc.author_name || "—"}</span> },
            { key: "date", header: "Date", align: "right", render: (doc) => doc.doc_date || "—" },
          ]}
        />
      )}
    </QueryState>
  );
}

function TimelineTab({ matterId }: { matterId: string }) {
  const timeline = useMatterTimeline(matterId);
  return (
    <QueryState query={timeline} isEmpty={(t) => t.length === 0} empty={<EmptyState icon="timeline" title="No dated documents on this matter" />}>
      {(events) => (
        <ol className="relative space-y-6 border-l border-border pl-6" data-testid="matter-timeline">
          {events.map((e) => (
            <li key={e.doc_id} className="relative">
              <span className="absolute -left-[27px] top-1 h-3 w-3 rounded-full border-2 border-wine bg-background" />
              <div className="font-mono-id text-xs text-wine">{e.date || "undated"}</div>
              <Link to={`/documents/${e.doc_id}`} className="mt-0.5 block text-base text-foreground hover:text-wine">
                {e.event}
              </Link>
              <div className="mt-0.5 text-xs text-muted-foreground">{[e.doc_type, e.author].filter(Boolean).join(" · ")}</div>
            </li>
          ))}
        </ol>
      )}
    </QueryState>
  );
}

function DeadlinesTab({ matterId }: { matterId: string }) {
  const deadlines = useDeadlines({ status: "all", matter_id: matterId });
  return (
    <QueryState query={deadlines} isEmpty={(d) => d.length === 0} empty={<EmptyState icon="event" title="No deadlines on this matter" />}>
      {(rows) => (
        <DataTable
          rows={rows}
          getRowKey={(d) => d.id}
          columns={[
            { key: "due", header: "Due", render: (d) => <span className="font-mono-id text-sm">{d.due}</span> },
            { key: "when", header: "", render: (d) => <span className="text-xs text-muted-foreground">{dueLabel(d.due)}</span> },
            { key: "title", header: "Deadline", render: (d) => d.title },
            { key: "owner", header: "Owner", render: (d) => d.owner_name || "—" },
            { key: "status", header: "Status", align: "right", render: (d) => <StatusLabel status={d.status === "done" ? "Resolved" : "Open"} /> },
          ]}
        />
      )}
    </QueryState>
  );
}

function ArgumentsTab({ matterId }: { matterId: string }) {
  const args = useMatterArguments(matterId);
  return (
    <QueryState query={args} isEmpty={(a) => a.length === 0} empty={<EmptyState icon="balance" title="No arguments recorded" />}>
      {(rows) => (
        <div className="space-y-px">
          {rows.map((a) => (
            <div key={a.argument_id} className="border-b border-border py-4">
              <div className="text-base text-foreground">{a.issue}</div>
              {a.position && <div className="mt-0.5 text-xs uppercase tracking-wide text-wine">{a.position}</div>}
              <p className="mt-1 text-sm text-muted-foreground">{a.argument}</p>
              {a.outcome && <p className="mt-1 text-xs text-muted-foreground">Outcome: {a.outcome}</p>}
            </div>
          ))}
        </div>
      )}
    </QueryState>
  );
}

function RelatedTab({ matterId }: { matterId: string }) {
  const navigate = useNavigate();
  const related = useMatterRelated(matterId);
  return (
    <QueryState query={related} isEmpty={(r) => r.length === 0} empty={<EmptyState icon="join_inner" title="No related matters in your scope" />}>
      {(rows) => (
        <DataTable
          rows={rows}
          getRowKey={(r) => r.matter_id}
          onRowClick={(r) => navigate(`/matters/${r.matter_id}`)}
          columns={[
            {
              key: "matter",
              header: "Matter",
              render: (r) => (
                <div>
                  <div className="font-mono-id text-xs text-muted-foreground">{r.matter_code}</div>
                  <div>{r.title}</div>
                </div>
              ),
            },
            { key: "client", header: "Client", render: (r) => r.client_name || "—" },
            { key: "status", header: "Status", align: "right", render: (r) => <StatusLabel status={r.status || "Open"} /> },
          ]}
        />
      )}
    </QueryState>
  );
}
