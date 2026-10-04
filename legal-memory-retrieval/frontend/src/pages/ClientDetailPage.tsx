import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { can, useMyAccess } from "@/api/access";
import { deleteClientNote, firmError } from "@/api/firm";
import { AddNoteDialog, EditClientDialog } from "@/components/clients/ClientEditors";
import { useConfirm } from "@/components/common/Confirm";
import { NewMatterDialog } from "@/components/matter/MatterEditors";
import { useApp } from "@/context/AppContext";
import { useQueryClient } from "@tanstack/react-query";
import { useClient } from "@/api/resources";
import type { ClientNote } from "@/api/types";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, MonoId, PageHeader, SectionLabel, StatusLabel, DetailSkeleton } from "@/components/common/primitives";
import { formatDate } from "@/lib/format";
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
  const access = useMyAccess();
  const mayEdit = can(access.data, "clients.create");
  const [editing, setEditing] = useState(false);
  const [noting, setNoting] = useState(false);
  const [newMatter, setNewMatter] = useState(false);
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const removeNote = async (noteId: string) => {
    if (!(await confirm({ title: "Remove this note?", confirmLabel: "Remove note" }))) return;
    try {
      await deleteClientNote(id, noteId);
      await queryClient.invalidateQueries({ queryKey: [identityKey, "client", id] });
    } catch (err) {
      toast(firmError(err));
    }
  };

  return (
    <QueryState query={client} loading={<DetailSkeleton />}>
      {(c) => (
        <div className="space-y-10">
          <PageHeader
            eyebrow="Client memory"
            title={c.name}
            subtitle="What the firm has observed working with this client — each note traceable to the matter it came from."
            actions={
              <>
                <Action to={`/ask?scope=${encodeURIComponent(c.name)}&scopeType=client`} primary icon="manage_search">
                  Ask about this client
                </Action>
                {mayEdit && c.status !== "inactive" && c.status !== "declined" && (
                  <Action onClick={() => setNewMatter(true)} icon="add" testId="client-new-matter">
                    New matter
                  </Action>
                )}
                {mayEdit && (
                  <Action onClick={() => setEditing(true)} icon="edit" testId="client-edit">
                    Edit
                  </Action>
                )}
              </>
            }
          >
            <div className="mt-3 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
              <MonoId className="text-sm">{c.client_id}</MonoId>
              {c.industry && <span>{c.industry}</span>}
              {c.headquarters && <span>{c.headquarters}</span>}
              {c.status && c.status !== "active" && (
                <span className="rounded bg-warning-soft px-1.5 text-warning-ink" data-testid="client-standing">{c.status.replace(/_/g, " ")}</span>
              )}
            </div>
          </PageHeader>

          <section>
            <SectionLabel
              right={mayEdit ? (
                <button type="button" onClick={() => setNoting(true)} className="text-xs font-semibold text-wine hover:underline" data-testid="client-add-note">
                  Add a note
                </button>
              ) : undefined}
            >
              Observed preferences
            </SectionLabel>
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
                          <li key={n.note_id} className="group text-sm leading-relaxed">
                            {n.text}
                            {mayEdit && (
                              <button type="button" onClick={() => void removeNote(n.note_id)} aria-label="Remove note" className="ml-1.5 text-xs text-muted-foreground opacity-0 hover:text-destructive focus:opacity-100 group-hover:opacity-100 [@media(hover:none)]:opacity-100">
                                Remove
                              </button>
                            )}
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
                { key: "opened", header: "Opened", render: (m) => <span className="whitespace-nowrap tabular-nums">{formatDate(m.opened_date)}</span> },
                { key: "status", header: "Status", align: "right", render: (m) => <StatusLabel status={m.status || "Open"} /> },
              ]}
            />
          </section>
          {editing && <EditClientDialog client={c} onClose={() => setEditing(false)} />}
          {noting && <AddNoteDialog client={c} onClose={() => setNoting(false)} />}
          {newMatter && <NewMatterDialog open defaultClientId={c.client_id} onClose={() => setNewMatter(false)} onCreated={(mid) => { setNewMatter(false); navigate(`/matters/${mid}`); }} />}
        </div>
      )}
    </QueryState>
  );
}
