import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import {
  SOURCE_LABEL,
  archivePlaybook,
  createPlaybook,
  duplicatePlaybook,
  publishPlaybook,
  sharePlaybook,
  updatePlaybook,
  usePlaybook,
  usePlaybooks,
  type Playbook,
  type PlaybookColumn,
  type PlaybookKind,
  type PlaybookSummary,
} from "@/api/playbooks";
import { FORMAT_LABEL, type AnswerFormat } from "@/api/tabular";
import { useMyAccess, can } from "@/api/access";
import { Markdown } from "@/components/chat/Markdown";
import { Field, fieldControl } from "@/components/common/Field";
import { PersonPicker } from "@/components/common/PersonPicker";
import { Chip, Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

/** The playbooks the member can use: built in, the firm's and their own (side view of the workbench). */
export function PlaybooksView({ onUse, onStartReview }: {
  onUse: (p: PlaybookSummary) => void;
  onStartReview: (p: PlaybookSummary) => void;
}) {
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<PlaybookKind | "">("");
  const list = usePlaybooks({ kind: kind || undefined, q });
  const [open, setOpen] = useState<string | null>(null);
  const [creating, setCreating] = useState<PlaybookKind | null>(null);
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-playbooks">
      <div className="space-y-2 border-b border-border px-3 py-2">
        <div className="flex items-center gap-1">
          <div className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Playbooks</div>
          <button type="button" className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" title="New instructions playbook"
            aria-label="New instructions playbook" onClick={() => setCreating("instructions")} data-testid="playbooks-new">
            <Icon name="add" style={{ fontSize: 17 }} />
          </button>
        </div>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a playbook" aria-label="Find a playbook"
          className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm focus-visible:outline-none" />
        <div className="flex gap-1 text-[11px]">
          {([["", "All"], ["instructions", "Instructions"], ["columns", "Review questions"]] as const).map(([k, l]) => (
            <button key={k} type="button" onClick={() => setKind(k)}
              className={cn("rounded px-2 py-0.5", kind === k ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}>{l}</button>
          ))}
        </div>
      </div>
      <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto">
        {(list.data ?? []).map((p) => (
          <li key={p.playbook_id}>
            <button type="button" className="w-full px-3 py-2 text-left hover:bg-secondary/70" onClick={() => setOpen(p.playbook_id)} data-testid="playbook-item">
              <div className="flex items-center gap-1.5 text-[13px] font-medium">
                <Icon name={p.kind === "columns" ? "view_column" : "menu_book"} className="text-muted-foreground" style={{ fontSize: 15 }} />
                <span className="truncate">{p.title}</span>
                <span className="ml-auto shrink-0 text-[10px] uppercase tracking-wide text-muted-foreground">{SOURCE_LABEL[p.source]}</span>
              </div>
              {p.summary && <p className="mt-0.5 line-clamp-2 text-[11px] text-muted-foreground">{p.summary}</p>}
            </button>
          </li>
        ))}
        {list.data && list.data.length === 0 && <li className="px-3 py-3 text-xs text-muted-foreground">No playbook matches.</li>}
      </ul>
      {open && <PlaybookDialog id={open} onClose={() => setOpen(null)} onOpenOther={setOpen}
        onUse={(p) => { setOpen(null); onUse(p); }} onStartReview={(p) => { setOpen(null); onStartReview(p); }} />}
      {creating && <EditPlaybookDialog kind={creating} onClose={() => setCreating(null)} onSaved={(p) => { setCreating(null); setOpen(p.playbook_id); }} />}
    </div>
  );
}

function PlaybookDialog({ id, onClose, onOpenOther, onUse, onStartReview }: {
  id: string; onClose: () => void; onOpenOther: (id: string) => void
  onUse: (p: PlaybookSummary) => void; onStartReview: (p: PlaybookSummary) => void
}) {
  const pb = usePlaybook(id);
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const access = useMyAccess();
  const [editing, setEditing] = useState(false);
  const [sharing, setSharing] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("playbooks") || q.queryKey.includes("playbook") });
  const act = async (fn: () => Promise<Playbook | unknown>, done: string) => {
    try {
      const out = await fn();
      await refresh();
      toast(done);
      return out;
    } catch (err) {
      toast(firmError(err));
    }
  };
  const p = pb.data;
  if (editing && p) return <EditPlaybookDialog kind={p.kind} playbook={p} onClose={() => setEditing(false)} onSaved={() => { setEditing(false); void refresh(); }} />;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[88vh] max-w-2xl overflow-y-auto" data-testid="playbook-dialog">
        {!p ? (
          <p className="text-sm text-muted-foreground">{pb.isError ? "This playbook is not available." : "Loading…"}</p>
        ) : (
          <>
            <DialogHeader>
              <DialogTitle>{p.title}</DialogTitle>
              <DialogDescription>
                {SOURCE_LABEL[p.source]} · {p.kind === "columns" ? `${p.columns.length} review questions` : "Instructions for the Assistant"}
                {p.practice_area ? ` · ${p.practice_area}` : ""}{p.version > 1 ? ` · version ${p.version}` : ""}
              </DialogDescription>
            </DialogHeader>
            {p.summary && <p className="text-sm">{p.summary}</p>}
            {p.kind === "columns" ? (
              <ol className="space-y-1.5 text-sm">
                {p.columns.map((c, i) => (
                  <li key={i} className="rounded-md border border-border px-3 py-1.5">
                    <span className="font-medium">{c.label}</span> <Chip className="ml-1">{FORMAT_LABEL[c.answer_format]}</Chip>
                    <div className="text-xs text-muted-foreground">{c.question}</div>
                  </li>
                ))}
              </ol>
            ) : (
              <div className="rounded-md border border-border bg-secondary/30 px-4 py-2"><Markdown text={p.body_md} paragraphClassName="my-1.5 text-sm" /></div>
            )}
            {p.files.length > 0 && (
              <div className="text-xs text-muted-foreground">Reference documents: {p.files.map((f) => f.title).join(" · ")}</div>
            )}
            <div className="flex flex-wrap gap-2 pt-1">
              {p.kind === "instructions" ? (
                <Button size="sm" onClick={() => onUse(p)} data-testid="playbook-use"><Icon name="play_arrow" style={{ fontSize: 16 }} /> Use with the Assistant</Button>
              ) : (
                <Button size="sm" onClick={() => onStartReview(p)} data-testid="playbook-start-review"><Icon name="table_chart" style={{ fontSize: 16 }} /> Start a review</Button>
              )}
              {p.my_level !== "read" && <Button size="sm" variant="outline" onClick={() => setEditing(true)}><Icon name="edit" style={{ fontSize: 16 }} /> Edit</Button>}
              <Button size="sm" variant="outline" data-testid="playbook-duplicate"
                onClick={async () => { const c = (await act(() => duplicatePlaybook(p.playbook_id), "Copied to your playbooks")) as Playbook | undefined; if (c) onOpenOther(c.playbook_id); }}>
                <Icon name="content_copy" style={{ fontSize: 16 }} /> Duplicate
              </Button>
              {p.source === "personal" && p.my_level === "manage" && (
                <Button size="sm" variant="ghost" onClick={() => setSharing((s) => !s)}><Icon name="share" style={{ fontSize: 16 }} /> Share</Button>
              )}
              {p.source === "personal" && p.my_level === "manage" && can(access.data, "km.publish") && (
                <Button size="sm" variant="ghost" onClick={() => void act(() => publishPlaybook(p.playbook_id), "Published for the firm")}>
                  <Icon name="public" style={{ fontSize: 16 }} /> Publish for the firm
                </Button>
              )}
              {p.source !== "shipped" && p.my_level === "manage" && (
                <Button size="sm" variant="ghost" className="text-destructive" onClick={() => void act(() => archivePlaybook(p.playbook_id), "Playbook removed").then(onClose)}>
                  Remove
                </Button>
              )}
            </div>
            {sharing && <ShareBox playbook={p} onChanged={refresh} />}
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ShareBox({ playbook, onChanged }: { playbook: Playbook; onChanged: () => void }) {
  const [person, setPerson] = useState<string | null>(null);
  const [level, setLevel] = useState<"view" | "edit">("view");
  const { toast } = useApp();
  const run = async (fn: () => Promise<unknown>) => {
    try { await fn(); onChanged(); } catch (err) { toast(firmError(err)); }
  };
  return (
    <div className="space-y-2 rounded-md bg-secondary/50 p-3">
      {playbook.shares.map((s) => (
        <div key={`${s.principal_type}:${s.principal_id}`} className="flex items-center gap-2 text-sm">
          <span className="flex-1 truncate">{s.name ?? s.principal_id}</span>
          <span className="text-xs text-muted-foreground">{s.level === "edit" ? "can edit" : "can use"}</span>
          <button type="button" aria-label="Stop sharing" onClick={() => run(() => sharePlaybook(playbook.playbook_id, { principal_type: s.principal_type, principal_id: s.principal_id, level: null }))}>
            <Icon name="close" style={{ fontSize: 15 }} />
          </button>
        </div>
      ))}
      <div className="grid grid-cols-[1fr_auto_auto] items-end gap-2">
        <PersonPicker value={person} onChange={setPerson} label="Share with" />
        <select value={level} onChange={(e) => setLevel(e.target.value as "view" | "edit")} className="h-9 rounded-md border border-border bg-card px-2 text-sm" aria-label="Access">
          <option value="view">Can use</option>
          <option value="edit">Can edit</option>
        </select>
        <Button size="sm" disabled={!person} onClick={() => person && run(async () => { await sharePlaybook(playbook.playbook_id, { principal_type: "member", principal_id: person, level }); setPerson(null); })}>Share</Button>
      </div>
    </div>
  );
}

function EditPlaybookDialog({ kind, playbook, onClose, onSaved }: { kind: PlaybookKind; playbook?: Playbook; onClose: () => void; onSaved: (p: Playbook) => void }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState(playbook?.title ?? "");
  const [summary, setSummary] = useState(playbook?.summary ?? "");
  const [area, setArea] = useState(playbook?.practice_area ?? "");
  const [body, setBody] = useState(playbook?.body_md ?? "");
  const [columns, setColumns] = useState<PlaybookColumn[]>(playbook?.columns?.length ? playbook.columns : [{ label: "", question: "", answer_format: "text", choices: [] }]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => setError(null), [title, body]);
  const save = async () => {
    setBusy(true);
    try {
      const data = {
        kind, title: title.trim(), summary: summary.trim() || undefined, practice_area: area.trim() || undefined,
        body_md: body, columns: kind === "columns" ? columns.filter((c) => c.label.trim() && c.question.trim()) : undefined,
      };
      const out = playbook ? await updatePlaybook(playbook.playbook_id, { ...data, row_version: playbook.row_version }) : await createPlaybook(data);
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("playbooks") || q.queryKey.includes("playbook") });
      toast("Playbook saved");
      onSaved(out);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto" data-testid="edit-playbook-dialog">
        <DialogHeader>
          <DialogTitle>{playbook ? "Edit playbook" : kind === "columns" ? "New review questions" : "New playbook"}</DialogTitle>
          <DialogDescription>
            {kind === "columns" ? "A set of questions that starts a tabular review." : "Write how the job is done, step by step. The Assistant reads it and follows it, asking for anything missing."}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Title" error={error}>{(p) => <input {...p} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={fieldControl} data-testid="playbook-title" />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Summary">{(p) => <input {...p} value={summary} onChange={(e) => setSummary(e.target.value)} maxLength={500} className={fieldControl} />}</Field>
            <Field label="Practice area">{(p) => <input {...p} value={area} onChange={(e) => setArea(e.target.value)} maxLength={100} className={fieldControl} />}</Field>
          </div>
          {kind === "instructions" ? (
            <Field label="Instructions (Markdown)">
              {(p) => <textarea {...p} value={body} onChange={(e) => setBody(e.target.value)} rows={14} maxLength={60000}
                className={cn(fieldControl, "font-mono text-[13px]")} placeholder={"1. Read the document in full.\n2. …"} data-testid="playbook-body" />}
            </Field>
          ) : (
            <div className="space-y-2">
              {columns.map((c, i) => (
                <div key={i} className="grid grid-cols-[1fr_2fr_auto_auto] gap-1.5">
                  <input value={c.label} onChange={(e) => setColumns(columns.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))} placeholder="Column" className={fieldControl} aria-label="Column name" />
                  <input value={c.question} onChange={(e) => setColumns(columns.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))} placeholder="Question" className={fieldControl} aria-label="Question" />
                  <select value={c.answer_format} onChange={(e) => setColumns(columns.map((x, j) => (j === i ? { ...x, answer_format: e.target.value as AnswerFormat } : x)))} className="h-9 rounded-md border border-border bg-card px-2 text-sm" aria-label="Answer as">
                    {Object.entries(FORMAT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
                  </select>
                  <button type="button" aria-label="Remove" onClick={() => setColumns(columns.filter((_, j) => j !== i))}><Icon name="close" style={{ fontSize: 16 }} /></button>
                </div>
              ))}
              <Button variant="ghost" size="sm" onClick={() => setColumns([...columns, { label: "", question: "", answer_format: "text", choices: [] }])}>
                <Icon name="add" style={{ fontSize: 16 }} /> Add a question
              </Button>
            </div>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || !title.trim()} onClick={save} data-testid="playbook-save">Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
