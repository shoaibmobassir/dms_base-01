import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  EVENT_KINDS,
  RELATIONS,
  ROLES,
  addArgument,
  addEvent,
  createMatter,
  deleteArgument,
  deleteEvent,
  firmError,
  linkMatter,
  removeStaff,
  setStaff,
  unlinkMatter,
  updateArgument,
  updateEvent,
  updateMatter,
  type MatterInput,
} from "@/api/firm";
import { useClients, useMatters, usePeople } from "@/api/resources";
import type { MatterArgument, MatterDetail, TeamMember, TimelineEvent } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";

const inputCls = "w-full rounded-md border border-border bg-card px-3 py-2 text-sm";

/** Run a write, report its outcome, and refresh what it changed. */
export function useFirmWrite(matterId?: string) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async <T,>(fn: () => Promise<T>, done?: string): Promise<T | undefined> => {
    setBusy(true);
    setError(null);
    try {
      const out = await fn();
      if (matterId) await queryClient.invalidateQueries({ queryKey: [identityKey, "matter", matterId] });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "matters"] });
      if (done) toast(done);
      return out;
    } catch (err) {
      setError(firmError(err));
      return undefined;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error, setError };
}

function Shell({ open, onClose, title, description, children, testId }: {
  open: boolean; onClose: () => void; title: string; description?: ReactNode; children: ReactNode; testId?: string;
}) {
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid={testId}>
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-3 text-sm">{children}</div>
      </DialogContent>
    </Dialog>
  );
}

function Footer({ busy, error, onCancel, onSubmit, label, disabled, testId }: {
  busy: boolean; error: string | null; onCancel: () => void; onSubmit: () => void; label: string; disabled?: boolean; testId?: string;
}) {
  return (
    <>
      {error && <p className="text-sm text-destructive" data-testid="form-error">{error}</p>}
      <div className="flex justify-end gap-2 pt-1">
        <Button variant="outline" onClick={onCancel}>Cancel</Button>
        <Button disabled={busy || disabled} onClick={onSubmit} data-testid={testId}>{busy ? "Saving…" : label}</Button>
      </div>
    </>
  );
}

const lines = (text: string) => text.split("\n").map((s) => s.trim()).filter(Boolean);

// ── new matter ───────────────────────────────────────────────────────────────

export function NewMatterDialog({ open, onClose, onCreated }: { open: boolean; onClose: () => void; onCreated: (id: string) => void }) {
  const { me } = useApp();
  const clients = useClients({});
  const people = usePeople();
  const { run, busy, error } = useFirmWrite();
  const [form, setForm] = useState<MatterInput>({ title: "", client_id: "", practice_area: "", access_mode: "team" });
  const [facts, setFacts] = useState("");
  const [team, setTeam] = useState<string[]>([]);
  const set = (patch: Partial<MatterInput>) => setForm((f) => ({ ...f, ...patch }));
  const active = (clients.data?.items ?? []).filter((c) => (c.status ?? "active") === "active");

  const submit = async () => {
    const out = await run(() => createMatter({
      ...form,
      client_id: form.client_id || active[0]?.client_id || "",
      facts: lines(facts),
      team: team.map((member_id) => ({ member_id, role: "Associate" })),
    }), "Matter opened");
    if (out) onCreated(out.matter_id);
  };

  return (
    <Shell open={open} onClose={onClose} title="Open a matter" testId="new-matter-dialog"
      description="You lead it unless you name another lead. New clients go through intake and a conflict check first.">
      <input className={inputCls} placeholder="Title" aria-label="Title" value={form.title} onChange={(e) => set({ title: e.target.value })} data-testid="new-matter-title" />
      <select className={inputCls} aria-label="Client" value={form.client_id} onChange={(e) => set({ client_id: e.target.value })} data-testid="new-matter-client">
        <option value="">Choose a client…</option>
        {active.map((c) => <option key={c.client_id} value={c.client_id}>{c.name}</option>)}
      </select>
      <div className="grid grid-cols-2 gap-2">
        <input className={inputCls} placeholder="Practice area" aria-label="Practice area" value={form.practice_area}
          onChange={(e) => set({ practice_area: e.target.value })} data-testid="new-matter-practice" />
        <input className={inputCls} placeholder="Office" aria-label="Office" value={form.office ?? ""} onChange={(e) => set({ office: e.target.value })} />
        <input className={inputCls} placeholder="Opposing party" aria-label="Opposing party" value={form.opposing_party ?? ""}
          onChange={(e) => set({ opposing_party: e.target.value })} />
        <input className={inputCls} placeholder="Forum / court" aria-label="Court" value={form.court ?? ""} onChange={(e) => set({ court: e.target.value })} />
      </div>
      <textarea className={`${inputCls} min-h-20`} placeholder="Key facts, one per line" value={facts} onChange={(e) => setFacts(e.target.value)} />
      <label className="block">
        <span className="text-xs text-muted-foreground">Who can see it</span>
        <select className={inputCls} value={form.access_mode} onChange={(e) => set({ access_mode: e.target.value as MatterInput["access_mode"] })}
          data-testid="new-matter-access">
          <option value="team">The matter team</option>
          <option value="open">Everyone in the firm</option>
          <option value="restricted">Restricted (named people only)</option>
        </select>
      </label>
      <label className="block">
        <span className="text-xs text-muted-foreground">Team (besides the lead)</span>
        <select multiple className={`${inputCls} h-28`} value={team}
          onChange={(e) => setTeam([...e.target.selectedOptions].map((o) => o.value))} data-testid="new-matter-team">
          {(people.data ?? []).filter((p) => p.member_id !== me?.member_id).map((p) => (
            <option key={p.member_id} value={p.member_id}>{p.name} — {p.role}</option>
          ))}
        </select>
      </label>
      <Footer busy={busy} error={error} onCancel={onClose} onSubmit={() => void submit()} label="Open matter"
        disabled={!form.title.trim() || !form.practice_area.trim()} testId="new-matter-submit" />
    </Shell>
  );
}

// ── edit / close ─────────────────────────────────────────────────────────────

export function EditMatterDialog({ detail, open, onClose }: { detail: MatterDetail; open: boolean; onClose: () => void }) {
  const m = detail.matter;
  const { run, busy, error } = useFirmWrite(m.matter_id);
  const [title, setTitle] = useState(m.title);
  const [status, setStatus] = useState(m.status || "Open");
  const [opposing, setOpposing] = useState(m.opposing_party ?? "");
  const [court, setCourt] = useState(m.court ?? "");
  const [outcome, setOutcome] = useState(m.outcome ?? "");
  const [facts, setFacts] = useState(m.facts.join("\n"));
  const [issues, setIssues] = useState(m.legal_issues.join("\n"));
  const submit = async () => {
    const changes: Record<string, unknown> = {};
    if (title !== m.title) changes.title = title;
    if (status !== (m.status || "Open")) changes.status = status;
    if (opposing !== (m.opposing_party ?? "")) changes.opposing_party = opposing;
    if (court !== (m.court ?? "")) changes.court = court;
    if (outcome !== (m.outcome ?? "")) changes.outcome = outcome;
    if (facts !== m.facts.join("\n")) changes.facts = lines(facts);
    if (issues !== m.legal_issues.join("\n")) changes.legal_issues = lines(issues);
    if (!Object.keys(changes).length) return onClose();
    const out = await run(() => updateMatter(m.matter_id, changes, m.row_version), "Matter updated");
    if (out) onClose();
  };
  return (
    <Shell open={open} onClose={onClose} title="Edit matter" testId="edit-matter-dialog">
      <input className={inputCls} aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} data-testid="edit-matter-title" />
      <div className="grid grid-cols-2 gap-2">
        <select className={inputCls} aria-label="Status" value={status} onChange={(e) => setStatus(e.target.value)} data-testid="edit-matter-status">
          {["Open", "On hold", "Closed"].map((s) => <option key={s}>{s}</option>)}
        </select>
        <input className={inputCls} placeholder="Opposing party" aria-label="Opposing party" value={opposing} onChange={(e) => setOpposing(e.target.value)} />
        <input className={`${inputCls} col-span-2`} placeholder="Forum / court" aria-label="Court" value={court} onChange={(e) => setCourt(e.target.value)} />
      </div>
      {status === "Closed" && <input className={inputCls} placeholder="Outcome" aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} />}
      <textarea className={`${inputCls} min-h-24`} placeholder="Key facts, one per line" value={facts} onChange={(e) => setFacts(e.target.value)} />
      <textarea className={`${inputCls} min-h-16`} placeholder="Legal issues, one per line" value={issues} onChange={(e) => setIssues(e.target.value)} />
      <Footer busy={busy} error={error} onCancel={onClose} onSubmit={() => void submit()} label="Save" disabled={!title.trim()} testId="edit-matter-save" />
    </Shell>
  );
}

// ── team ─────────────────────────────────────────────────────────────────────

export function TeamEditor({ matterId, team, canManage }: { matterId: string; team: TeamMember[]; canManage: boolean }) {
  const people = usePeople();
  const { run, busy, error } = useFirmWrite(matterId);
  const [adding, setAdding] = useState("");
  const [role, setRole] = useState<string>("Associate");
  const onTeam = new Set(team.map((t) => t.member_id));
  const save = (t: TeamMember, patch: Partial<Pick<TeamMember, "role_on_matter" | "started_at" | "ended_at">>) =>
    run(() => setStaff(matterId, t.member_id, {
      role: patch.role_on_matter ?? t.role_on_matter,
      started_at: (patch.started_at !== undefined ? patch.started_at : t.started_at) || null,
      ended_at: (patch.ended_at !== undefined ? patch.ended_at : t.ended_at) || null,
    }), "Team updated");
  return (
    <div className="space-y-3" data-testid="team-editor">
      <div className="overflow-hidden rounded-lg border border-border">
        <table className="w-full text-sm">
          <thead className="bg-secondary/50 text-left text-xs uppercase tracking-wide text-muted-foreground">
            <tr><th className="px-3 py-2">Person</th><th className="px-3 py-2">Role</th><th className="px-3 py-2">From</th><th className="px-3 py-2">Until</th><th /></tr>
          </thead>
          <tbody>
            {team.map((t) => (
              <tr key={t.member_id} className={t.active === false ? "text-muted-foreground" : ""} data-testid="team-row">
                <td className="px-3 py-2">
                  {t.name}
                  {t.active === false && <span className="ml-2 rounded bg-secondary px-1.5 text-[11px]">ended</span>}
                </td>
                <td className="px-3 py-2">
                  {canManage ? (
                    <select className="rounded border border-border bg-background px-1 py-0.5" value={t.role_on_matter}
                      onChange={(e) => void save(t, { role_on_matter: e.target.value })} disabled={busy} aria-label={`Role of ${t.name}`}>
                      {ROLES.map((r) => <option key={r}>{r}</option>)}
                    </select>
                  ) : t.role_on_matter}
                </td>
                <td className="px-3 py-2">
                  {canManage ? <input type="date" className="rounded border border-border bg-background px-1" value={t.started_at ?? ""}
                    onChange={(e) => void save(t, { started_at: e.target.value || null })} aria-label={`Start of ${t.name}`} /> : t.started_at ?? "—"}
                </td>
                <td className="px-3 py-2">
                  {canManage ? <input type="date" className="rounded border border-border bg-background px-1" value={t.ended_at ?? ""}
                    onChange={(e) => void save(t, { ended_at: e.target.value || null })} aria-label={`End of ${t.name}`} data-testid="team-ended" /> : t.ended_at ?? "—"}
                </td>
                <td className="px-3 py-2 text-right">
                  {canManage && t.role_on_matter.toLowerCase() !== "lead" && (
                    <button type="button" aria-label={`Remove ${t.name}`} className="rounded p-1 hover:bg-secondary"
                      onClick={() => void run(() => removeStaff(matterId, t.member_id), "Removed from the team")}>
                      <Icon name="close" style={{ fontSize: 16 }} />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {canManage && (
        <div className="flex flex-wrap items-center gap-2">
          <select className="rounded-md border border-border bg-card px-2 py-1.5 text-sm" value={adding} onChange={(e) => setAdding(e.target.value)}
            aria-label="Add to team" data-testid="team-add-person">
            <option value="">Add someone…</option>
            {(people.data ?? []).filter((p) => !onTeam.has(p.member_id)).map((p) => <option key={p.member_id} value={p.member_id}>{p.name}</option>)}
          </select>
          <select className="rounded-md border border-border bg-card px-2 py-1.5 text-sm" value={role} onChange={(e) => setRole(e.target.value)} aria-label="Role">
            {ROLES.filter((r) => r !== "Lead").map((r) => <option key={r}>{r}</option>)}
          </select>
          <Button size="sm" disabled={!adding || busy} data-testid="team-add"
            onClick={() => void run(() => setStaff(matterId, adding, { role, started_at: new Date().toISOString().slice(0, 10) }), "Added to the team").then(() => setAdding(""))}>
            Add
          </Button>
          <span className="text-xs text-muted-foreground">An end date removes team access from the next day.</span>
        </div>
      )}
      {error && <p className="text-sm text-destructive" data-testid="form-error">{error}</p>}
    </div>
  );
}

// ── timeline entries ─────────────────────────────────────────────────────────

export function TimelineEntryDialog({ matterId, entry, open, onClose }: { matterId: string; entry?: TimelineEvent; open: boolean; onClose: () => void }) {
  const { run, busy, error } = useFirmWrite(matterId);
  const [date, setDate] = useState(entry?.date ?? new Date().toISOString().slice(0, 10));
  const [title, setTitle] = useState(entry?.event ?? "");
  const [kind, setKind] = useState(entry?.doc_type?.toLowerCase() ?? "event");
  const [detail, setDetail] = useState(entry?.detail ?? "");
  const submit = async () => {
    const body = { occurred_on: date, title, kind, detail };
    const out = entry?.event_id
      ? await run(() => updateEvent(matterId, entry.event_id!, { ...body, row_version: entry.row_version }), "Timeline updated")
      : await run(() => addEvent(matterId, body), "Added to the timeline");
    if (out) onClose();
  };
  return (
    <Shell open={open} onClose={onClose} title={entry ? "Edit timeline entry" : "Add to the timeline"} testId="timeline-dialog">
      <div className="grid grid-cols-2 gap-2">
        <input type="date" className={inputCls} aria-label="Date" value={date} onChange={(e) => setDate(e.target.value)} data-testid="timeline-date" />
        <select className={inputCls} aria-label="Kind" value={kind} onChange={(e) => setKind(e.target.value)}>
          {EVENT_KINDS.map((k) => <option key={k} value={k}>{k[0].toUpperCase() + k.slice(1)}</option>)}
        </select>
      </div>
      <input className={inputCls} placeholder="What happened" aria-label="Title" value={title} onChange={(e) => setTitle(e.target.value)} data-testid="timeline-title" />
      <textarea className={`${inputCls} min-h-20`} placeholder="Details (optional)" value={detail} onChange={(e) => setDetail(e.target.value)} />
      <Footer busy={busy} error={error} onCancel={onClose} onSubmit={() => void submit()} label="Save" disabled={!title.trim() || !date} testId="timeline-save" />
    </Shell>
  );
}

export function useDeleteTimelineEntry(matterId: string) {
  const { run } = useFirmWrite(matterId);
  return (eventId: string) => run(() => deleteEvent(matterId, eventId), "Removed from the timeline");
}

// ── arguments ────────────────────────────────────────────────────────────────

export function ArgumentDialog({ matterId, arg, open, onClose }: { matterId: string; arg?: MatterArgument; open: boolean; onClose: () => void }) {
  const { run, busy, error } = useFirmWrite(matterId);
  const [issue, setIssue] = useState(arg?.issue ?? "");
  const [position, setPosition] = useState(arg?.position ?? "");
  const [text, setText] = useState(arg?.argument ?? "");
  const [outcome, setOutcome] = useState(arg?.outcome ?? "");
  const submit = async () => {
    const body = { issue, position, argument: text, outcome };
    const out = arg
      ? await run(() => updateArgument(matterId, arg.argument_id, { ...body, row_version: arg.row_version }), "Argument updated")
      : await run(() => addArgument(matterId, body), "Argument recorded");
    if (out) onClose();
  };
  return (
    <Shell open={open} onClose={onClose} title={arg ? "Edit argument" : "Record an argument"} testId="argument-dialog">
      <input className={inputCls} placeholder="Issue" aria-label="Issue" value={issue} onChange={(e) => setIssue(e.target.value)} data-testid="argument-issue" />
      <input className={inputCls} placeholder="Whose position (e.g. our client, opposing party)" aria-label="Position" value={position} onChange={(e) => setPosition(e.target.value)} />
      <textarea className={`${inputCls} min-h-28`} placeholder="The argument" value={text} onChange={(e) => setText(e.target.value)} data-testid="argument-text" />
      <input className={inputCls} placeholder="Outcome (if decided)" aria-label="Outcome" value={outcome} onChange={(e) => setOutcome(e.target.value)} />
      <Footer busy={busy} error={error} onCancel={onClose} onSubmit={() => void submit()} label="Save" disabled={!issue.trim() || !text.trim()} testId="argument-save" />
    </Shell>
  );
}

export function useDeleteArgument(matterId: string) {
  const { run } = useFirmWrite(matterId);
  return (argId: string) => run(() => deleteArgument(matterId, argId), "Argument removed");
}

// ── related matters ──────────────────────────────────────────────────────────

export function LinkMatterDialog({ matterId, open, onClose }: { matterId: string; open: boolean; onClose: () => void }) {
  const { run, busy, error } = useFirmWrite(matterId);
  const [q, setQ] = useState("");
  const [target, setTarget] = useState("");
  const [relation, setRelation] = useState<string>("related");
  const [note, setNote] = useState("");
  const matters = useMatters({ q: q || undefined, limit: 20 });
  const submit = async () => {
    const out = await run(() => linkMatter(matterId, target, relation, note), "Matters linked");
    if (out) onClose();
  };
  return (
    <Shell open={open} onClose={onClose} title="Link a related matter" testId="link-dialog"
      description="You need edit access to both matters: the link shows each to the other's team.">
      <input className={inputCls} placeholder="Find a matter…" value={q} onChange={(e) => setQ(e.target.value)} data-testid="link-search" />
      <select className={`${inputCls} h-32`} size={6} value={target} onChange={(e) => setTarget(e.target.value)} data-testid="link-target">
        {(matters.data?.items ?? []).filter((m) => m.matter_id !== matterId).map((m) => (
          <option key={m.matter_id} value={m.matter_id}>{m.matter_code} — {m.title}</option>
        ))}
      </select>
      <select className={inputCls} value={relation} onChange={(e) => setRelation(e.target.value)} aria-label="Relation">
        {RELATIONS.map((r) => <option key={r} value={r}>{r.replace(/_/g, " ")}</option>)}
      </select>
      <input className={inputCls} placeholder="Why (optional)" value={note} onChange={(e) => setNote(e.target.value)} />
      <Footer busy={busy} error={error} onCancel={onClose} onSubmit={() => void submit()} label="Link" disabled={!target} testId="link-save" />
    </Shell>
  );
}

export function useUnlinkMatter(matterId: string) {
  const { run } = useFirmWrite(matterId);
  return (relatedId: string) => run(() => unlinkMatter(matterId, relatedId), "Link removed");
}
