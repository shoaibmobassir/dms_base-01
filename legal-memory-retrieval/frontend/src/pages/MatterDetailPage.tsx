import { useMatterAccessStatus } from "@/api/access";
import { ApiError } from "@/api/client";
import { LockedMatter } from "@/components/access/LockedMatter";
import { MatterAccessTab } from "@/components/access/MatterAccessTab";
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
import { useStartConversation } from "@/components/chat/useStartConversation";
import { formatDate } from "@/lib/format";
import { ClientLink } from "@/components/common/EntityLink";
import { Action, EmptyState, Icon, MonoId, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { useApp } from "@/context/AppContext";
import { dueLabel } from "@/pages/CalendarPage";
import { cn } from "@/lib/utils";
import {
  ArgumentDialog,
  EditMatterDialog,
  LinkMatterDialog,
  TeamEditor,
  TimelineEntryDialog,
  useDeleteArgument,
  useDeleteTimelineEntry,
  useUnlinkMatter,
} from "@/components/matter/MatterEditors";
import type { MatterArgument, TimelineEvent } from "@/api/types";

const TABS = ["Overview", "Documents", "Timeline", "Deadlines", "People", "Arguments", "Related", "Access"] as const;
type Tab = (typeof TABS)[number];

export function MatterDetailPage() {
  const { id = "" } = useParams();
  const matter = useMatter(id);

  if (matter.isError && matter.error instanceof ApiError && matter.error.status === 404) {
    return <LockedMatter matterId={id} />;
  }
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

function AssistantAction({ matterId }: { matterId: string }) {
  const { start } = useStartConversation();
  return (
    <Action onClick={() => start(matterId)} icon="edit_note" testId="matter-assistant">
      Work on it in Assistant
    </Action>
  );
}

function MatterView({ detail }: { detail: MatterDetail }) {
  const { matter: m, team } = detail;
  const [tab, setTab] = useState<Tab>("Overview");
  const status = useMatterAccessStatus(m.matter_id, true);
  const tabs = TABS.filter((t) => t !== "Access" || status.data?.level === "manage");
  const level = detail.my_level ?? "read";
  const canEdit = level === "edit" || level === "manage";
  const canManage = level === "manage";
  const [editing, setEditing] = useState(false);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Matter"
        title={m.title}
        subtitle={m.client_name ? <ClientLink id={m.client_id} name={m.client_name} /> : undefined}
        actions={
          <>
            <Action to={`/ask?scope=${encodeURIComponent(m.matter_code)}&scopeType=matter`} primary icon="manage_search" testId="matter-ask">
              Ask about this matter
            </Action>
            <AssistantAction matterId={m.matter_id} />
            <PinAction matterId={m.matter_id} />
            {canManage && (
              <Action onClick={() => setEditing(true)} icon="edit" testId="matter-edit">
                Edit
              </Action>
            )}
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
          {tabs.map((t) => (
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
        {tab === "Timeline" && <TimelineTab matterId={m.matter_id} canEdit={canEdit} />}
        {tab === "Deadlines" && <DeadlinesTab matterId={m.matter_id} />}
        {tab === "People" && <TeamEditor matterId={m.matter_id} team={team} canManage={canManage} />}
        {tab === "Arguments" && <ArgumentsTab matterId={m.matter_id} canEdit={canEdit} />}
        {tab === "Related" && <RelatedTab matterId={m.matter_id} canEdit={canEdit} />}
        {tab === "Access" && <MatterAccessTab matterId={m.matter_id} />}
      </div>
      {editing && <EditMatterDialog detail={detail} open onClose={() => setEditing(false)} />}
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
            <Field label="Opened">{formatDate(m.opened_date, "")}</Field>
            {m.closed_date && <Field label="Closed">{formatDate(m.closed_date)}</Field>}
            {m.outcome && <Field label="Outcome">{m.outcome}</Field>}
          </dl>
        </div>
        <div className="rounded-lg border border-border bg-card p-5">
          <SectionLabel>Team</SectionLabel>
          <div className="space-y-2.5">
            {team.length === 0 && <p className="text-sm text-muted-foreground">No team recorded.</p>}
            {[...team]
              .sort((a, b) => Number(b.role_on_matter?.toLowerCase() === "lead") - Number(a.role_on_matter?.toLowerCase() === "lead"))
              .map((tm) => (
                <div key={tm.member_id} className="text-sm" data-testid="matter-team-member">
                  <Link to={`/people/${tm.member_id}`} className="font-medium hover:text-wine">
                    {tm.name}
                  </Link>
                  {tm.role_on_matter?.toLowerCase() === "lead" && (
                    <span className="ml-1.5 rounded bg-wine px-1 py-px align-middle text-[10px] font-semibold uppercase text-primary-foreground">Lead</span>
                  )}
                  <div className="text-xs text-muted-foreground">{[tm.role, tm.office].filter(Boolean).join(" · ")}</div>
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
            { key: "date", header: "Date", align: "right", render: (doc) => <span className="whitespace-nowrap tabular-nums">{formatDate(doc.doc_date)}</span> },
          ]}
        />
      )}
    </QueryState>
  );
}

function TimelineTab({ matterId, canEdit }: { matterId: string; canEdit: boolean }) {
  const timeline = useMatterTimeline(matterId);
  const [dialog, setDialog] = useState<{ entry?: TimelineEvent } | null>(null);
  const remove = useDeleteTimelineEntry(matterId);
  return (
    <div className="space-y-4">
      {canEdit && (
        <Action onClick={() => setDialog({})} icon="add" testId="timeline-add">
          Add to the timeline
        </Action>
      )}
      <QueryState query={timeline} isEmpty={(t) => t.length === 0} empty={<EmptyState icon="timeline" title="Nothing on the timeline yet" />}>
        {(events) => (
          <ol className="relative space-y-6 border-l border-border pl-6" data-testid="matter-timeline">
            {events.map((e) => (
              <li key={e.event_id ?? `${e.doc_id}-${e.date}`} className="group relative" data-testid={e.source === "entry" ? "timeline-entry" : undefined}>
                <span className={cn("absolute -left-[27px] top-1 h-3 w-3 rounded-full border-2 bg-background",
                  e.source === "entry" ? "border-amber-500" : "border-wine")} />
                <div className="font-mono-id text-xs text-wine">{e.date || "undated"}</div>
                {e.doc_id ? (
                  <Link to={`/documents/${e.doc_id}`} className="mt-0.5 block text-base text-foreground hover:text-wine">{e.event}</Link>
                ) : (
                  <div className="mt-0.5 text-base text-foreground">{e.event}</div>
                )}
                {e.detail && <p className="mt-0.5 text-sm text-muted-foreground">{e.detail}</p>}
                <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                  {[e.doc_type, e.author].filter(Boolean).join(" · ")}
                  {canEdit && e.source === "entry" && e.event_id && (
                    <span className="opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                      <button type="button" className="underline" onClick={() => setDialog({ entry: e })}>Edit</button>{" "}
                      <button type="button" className="underline" onClick={() => void remove(e.event_id!)}>Delete</button>
                    </span>
                  )}
                </div>
              </li>
            ))}
          </ol>
        )}
      </QueryState>
      {dialog && <TimelineEntryDialog matterId={matterId} entry={dialog.entry} open onClose={() => setDialog(null)} />}
    </div>
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

function ArgumentsTab({ matterId, canEdit }: { matterId: string; canEdit: boolean }) {
  const args = useMatterArguments(matterId);
  const [dialog, setDialog] = useState<{ arg?: MatterArgument } | null>(null);
  const remove = useDeleteArgument(matterId);
  return (
    <div className="space-y-4">
      {canEdit && (
        <Action onClick={() => setDialog({})} icon="add" testId="argument-add">
          Record an argument
        </Action>
      )}
      <QueryState query={args} isEmpty={(a) => a.length === 0} empty={<EmptyState icon="balance" title="No arguments recorded" />}>
        {(rows) => (
          <div className="space-y-px" data-testid="matter-arguments">
            {rows.map((a) => (
              <div key={a.argument_id} className="group border-b border-border py-4">
                <div className="text-base text-foreground">{a.issue}</div>
                {a.position && <div className="mt-0.5 text-xs uppercase tracking-wide text-wine">{a.position}</div>}
                <p className="mt-1 text-sm text-muted-foreground">{a.argument}</p>
                {a.outcome && <p className="mt-1 text-xs text-muted-foreground">Outcome: {a.outcome}</p>}
                {canEdit && (
                  <div className="mt-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100 focus-within:opacity-100">
                    <button type="button" className="underline" onClick={() => setDialog({ arg: a })}>Edit</button>{" "}
                    <button type="button" className="underline" onClick={() => void remove(a.argument_id)}>Delete</button>
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </QueryState>
      {dialog && <ArgumentDialog matterId={matterId} arg={dialog.arg} open onClose={() => setDialog(null)} />}
    </div>
  );
}

function RelatedTab({ matterId, canEdit }: { matterId: string; canEdit: boolean }) {
  const navigate = useNavigate();
  const related = useMatterRelated(matterId);
  const [linking, setLinking] = useState(false);
  const unlink = useUnlinkMatter(matterId);
  return (
    <div className="space-y-4">
      {canEdit && (
        <Action onClick={() => setLinking(true)} icon="add_link" testId="related-add">
          Link a matter
        </Action>
      )}
      <QueryState query={related} isEmpty={(r) => r.length === 0} empty={<EmptyState icon="join_inner" title="No related matters in your scope" />}>
        {(rows) => (
          <DataTable
            testId="matter-related"
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
              {
                key: "why",
                header: "Relation",
                render: (r) => (
                  <span className="text-sm text-muted-foreground">
                    {(r.relation ?? "").replace(/_/g, " ")}
                    {r.manual && <span className="ml-1 rounded bg-secondary px-1 text-[11px]">linked</span>}
                    {r.note && <span className="block text-xs">{r.note}</span>}
                  </span>
                ),
              },
              { key: "client", header: "Client", render: (r) => r.client_name || "—" },
              {
                key: "status",
                header: "Status",
                align: "right",
                render: (r) => (
                  <span className="inline-flex items-center gap-2">
                    <StatusLabel status={r.status || "Open"} />
                    {canEdit && r.manual && (
                      <button type="button" aria-label="Remove link" className="rounded p-0.5 hover:bg-secondary"
                        onClick={(ev) => { ev.stopPropagation(); void unlink(r.matter_id); }}>
                        <Icon name="link_off" style={{ fontSize: 16 }} />
                      </button>
                    )}
                  </span>
                ),
              },
            ]}
          />
        )}
      </QueryState>
      {linking && <LinkMatterDialog matterId={matterId} open onClose={() => setLinking(false)} />}
    </div>
  );
}
