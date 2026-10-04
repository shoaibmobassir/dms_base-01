import { useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  Check,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  CircleDashed,
  Download,
  Eye,
  FileText,
  HelpCircle,
  Loader2,
  PencilLine,
  Upload,
  X,
  XCircle,
} from "lucide-react";
import { toast } from "sonner";
import { Icon } from "@/components/common/primitives";
import { ApiError, authHeaders } from "@/api/client";
import { decideAllEdits, decideEdit, exportEdits } from "@/api/chat";
import { addComment } from "@/api/editor";
import type { AskInputItem, Attachment, ChatEvent, EditProposal } from "@/api/types";
import { cn } from "@/lib/utils";

export function errorText(err: unknown, fallback: string): string {
  if (err instanceof ApiError) {
    try {
      const detail = (JSON.parse(err.message) as { detail?: unknown }).detail;
      if (typeof detail === "string") return detail;
    } catch {
      // not JSON
    }
  }
  return err instanceof Error && err.message ? err.message : fallback;
}

// ── step timeline ─────────────────────────────────────────────────────────────

type Step = {
  key: string;
  label: string;
  state: "running" | "done" | "failed" | "info";
  detail?: string;
  files?: string[];
};

const s = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`;

function detailOf(ev: ChatEvent): Pick<Step, "detail" | "files"> {
  switch (ev.type) {
    case "search_results": {
      const names = Array.isArray(ev.filenames) ? (ev.filenames as string[]) : [];
      return { detail: `${s(Number(ev.count ?? names.length), "record")} found`, files: names };
    }
    case "doc_find":
      return { detail: `${s(Number(ev.total_matches ?? 0), "match")}` };
    case "doc_created":
      return { detail: String(ev.filename ?? "File ready") };
    case "edit_proposals":
      return { detail: s(Array.isArray(ev.edits) ? ev.edits.length : 0, "suggested edit") };
    case "authority_results": {
      const names = Array.isArray(ev.citations) ? (ev.citations as string[]) : [];
      const n = Number(ev.count ?? names.length);
      return { detail: `${n} ${n === 1 ? "authority" : "authorities"} found`, files: names };
    }
    case "authority_status":
      return { detail: String(ev.display ?? "") };
    case "citation_check": {
      const summary = (ev.summary ?? {}) as Record<string, number>;
      const labels: Record<string, string> = {
        verified: "verified",
        verified_with_caution: "with caution",
        negative_treatment: "negative treatment",
        not_verified: "not verified",
      };
      const parts = Object.entries(summary).map(([k, n]) => `${n} ${labels[k] ?? k}`);
      return { detail: parts.join(" · ") || "No citations found" };
    }
    default:
      return {};
  }
}

/** Legacy steps (saved before start/finish events existed). */
function legacyLabel(ev: ChatEvent): string {
  const name = String(ev.filename ?? ev.title ?? "");
  switch (ev.type) {
    case "doc_read":
      return `Read ${name || "a document"}`;
    case "doc_find":
      return `Searched for “${String(ev.query ?? "")}”`;
    case "doc_created":
      return `Created ${name || "a document"}`;
    case "search_results":
      return `Searched firm records for “${String(ev.query ?? "")}”`;
    case "edit_proposals":
      return `Suggested edits to ${name || "a document"}`;
    default:
      return ev.type.replace(/_/g, " ");
  }
}

export function buildSteps(events: ChatEvent[]): Step[] {
  const steps: Step[] = [];
  const byCall = new Map<string, Step>();
  for (const ev of events) {
    const callId = typeof ev.call_id === "string" ? ev.call_id : null;
    if (ev.type === "reasoning") {
      steps.push({ key: `r${steps.length}`, label: String(ev.text ?? "Thinking"), state: "info" });
    } else if (ev.type === "tool_started" && callId) {
      const step: Step = { key: callId, label: String(ev.label ?? "Working"), state: "running" };
      byCall.set(callId, step);
      steps.push(step);
    } else if (ev.type === "tool_finished" && callId) {
      const step = byCall.get(callId);
      if (step) {
        step.state = ev.ok === false ? "failed" : "done";
        if (ev.ok === false && ev.error) step.detail = String(ev.error);
      }
    } else if (ev.type === "stopped") {
      steps.push({ key: `s${steps.length}`, label: "Stopped by you", state: "info" });
    } else if (ev.type === "ask_inputs") {
      if (!callId || !byCall.has(callId)) steps.push({ key: `a${steps.length}`, label: "Asked you to clarify", state: "done" });
    } else {
      const step = callId ? byCall.get(callId) : undefined;
      if (step) Object.assign(step, detailOf(ev));
      else steps.push({ key: `l${steps.length}`, label: legacyLabel(ev), state: "done", ...detailOf(ev) });
    }
  }
  return steps;
}

export function StepTimeline({ events, streaming }: { events: ChatEvent[]; streaming: boolean }) {
  const steps = useMemo(() => buildSteps(events), [events]);
  const [open, setOpen] = useState(false);
  if (!steps.length) return null;
  const expanded = open || streaming;
  const running = [...steps].reverse().find((st) => st.state === "running");
  // Say what was done ("Searched the firm's records, and 2 more steps"), not how many steps ran.
  const actions = steps.filter((st) => st.state !== "info");
  const summary = streaming
    ? (running ?? steps[steps.length - 1]).label
    : actions.length === 1
      ? actions[0].label
      : actions.length > 1
        ? `${actions[0].label}, and ${s(actions.length - 1, "more step")}`
        : steps[steps.length - 1].label;

  return (
    <div className="mb-3 text-xs" data-testid="step-timeline">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="inline-flex max-w-full items-center gap-1 text-muted-foreground hover:text-foreground"
      >
        {expanded ? <ChevronDown className="h-3.5 w-3.5 shrink-0" /> : <ChevronRight className="h-3.5 w-3.5 shrink-0" />}
        {streaming && <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin text-wine" />}
        <span className="truncate">{summary}</span>
      </button>
      {expanded && (
        <ol className="mt-2 space-y-1.5 border-l border-border pl-3">
          {steps.map((st) => (
            <li key={st.key} className="flex items-start gap-2" data-testid="step" data-state={st.state}>
              <span className="mt-px shrink-0">
                {st.state === "running" ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-wine" />
                ) : st.state === "failed" ? (
                  <XCircle className="h-3.5 w-3.5 text-destructive" />
                ) : st.state === "done" ? (
                  <CheckCircle2 className="h-3.5 w-3.5 text-success-ink" />
                ) : (
                  <CircleDashed className="h-3.5 w-3.5 text-muted-foreground" />
                )}
              </span>
              <div className="min-w-0">
                <div className={cn("text-[12px]", st.state === "info" ? "text-muted-foreground" : "text-foreground/85")}>{st.label}</div>
                {st.detail && <div className="text-xs text-muted-foreground">{st.detail}</div>}
                {st.files && st.files.length > 0 && (
                  <ul className="mt-0.5 space-y-px text-xs text-muted-foreground">
                    {st.files.slice(0, 5).map((f) => (
                      <li key={f} className="truncate">
                        · {f}
                      </li>
                    ))}
                    {st.files.length > 5 && <li>· and {st.files.length - 5} more</li>}
                  </ul>
                )}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

// ── clarifying questions ──────────────────────────────────────────────────────

export function AskInputsCard({
  items,
  answered,
  onSubmit,
  onUpload,
}: {
  items: AskInputItem[];
  answered: boolean;
  onSubmit: (text: string, files: Attachment[]) => void;
  onUpload: (file: File) => Promise<Attachment | null>;
}) {
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [files, setFiles] = useState<Record<string, Attachment[]>>({});
  const [uploading, setUploading] = useState<string | null>(null);
  const fileInputs = useRef<Record<string, HTMLInputElement | null>>({});

  const complete = items.every((it) =>
    it.kind === "documents" ? (files[it.id]?.length ?? 0) > 0 : (answers[it.id] ?? "").trim().length > 0,
  );

  const submit = () => {
    const lines = items.map((it) => {
      const q = it.question ?? it.id;
      const a = it.kind === "documents" ? (files[it.id] ?? []).map((f) => f.filename).join(", ") : answers[it.id];
      return `${q}\n→ ${a}`;
    });
    onSubmit(lines.join("\n\n"), Object.values(files).flat());
  };

  return (
    <div className="mb-3 rounded-lg border border-wine/25 bg-wine-soft/30 p-3" data-testid="ask-inputs">
      <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-ink">
        <HelpCircle className="h-3.5 w-3.5 text-wine" />
        {answered ? "You answered these questions" : "A few details before I continue"}
      </div>
      <div className="space-y-3">
        {items.map((it) => (
          <div key={it.id} className="space-y-1.5">
            {it.question && <p className="text-[13px] text-foreground">{it.question}</p>}
            {it.kind === "choice" && (
              <div className="flex flex-wrap gap-1.5">
                {(it.options ?? []).map((o) => (
                  <button
                    key={o.value}
                    type="button"
                    disabled={answered}
                    onClick={() => setAnswers((a) => ({ ...a, [it.id]: o.value }))}
                    data-testid="ask-option"
                    className={cn(
                      "rounded-full border px-2.5 py-0.5 text-[12px] transition-colors disabled:opacity-60",
                      answers[it.id] === o.value
                        ? "border-wine/50 bg-wine text-white"
                        : "border-border bg-card text-foreground hover:bg-secondary",
                    )}
                  >
                    {o.value}
                  </button>
                ))}
              </div>
            )}
            {(it.kind === "text" || (it.kind === "choice" && !(it.options ?? []).length)) && (
              <textarea
                rows={2}
                disabled={answered}
                value={answers[it.id] ?? ""}
                onChange={(e) => setAnswers((a) => ({ ...a, [it.id]: e.target.value }))}
                data-testid="ask-text"
                className="w-full resize-none rounded-md border border-border bg-card px-2 py-1.5 text-[13px] focus:outline-none"
              />
            )}
            {it.kind === "documents" && (
              <div className="flex flex-wrap items-center gap-1.5">
                <input
                  ref={(el) => {
                    fileInputs.current[it.id] = el;
                  }}
                  type="file"
                  accept=".pdf,.docx,.txt"
                  className="hidden"
                  onChange={async (e) => {
                    const file = e.target.files?.[0];
                    e.target.value = "";
                    if (!file) return;
                    setUploading(it.id);
                    const att = await onUpload(file);
                    setUploading(null);
                    if (att) setFiles((f) => ({ ...f, [it.id]: [...(f[it.id] ?? []), att] }));
                  }}
                />
                <button
                  type="button"
                  disabled={answered || uploading === it.id}
                  onClick={() => fileInputs.current[it.id]?.click()}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-[12px] hover:bg-secondary disabled:opacity-60"
                >
                  {uploading === it.id ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Upload className="h-3.5 w-3.5" />}
                  Attach a document
                </button>
                {(files[it.id] ?? []).map((f) => (
                  <span key={f.document_id} className="rounded bg-secondary px-1.5 py-0.5 text-xs">
                    {f.filename}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
      {!answered && (
        <button
          type="button"
          disabled={!complete}
          onClick={submit}
          data-testid="ask-submit"
          className="mt-3 rounded-md bg-primary px-3 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
        >
          Continue
        </button>
      )}
    </div>
  );
}

// ── suggested edits ───────────────────────────────────────────────────────────

export type EditGroup = {
  document_id: string;
  filename: string;
  edits: EditProposal[];
  /** "paragraph": document-wide edits from edit_document (tracked in the original file on export). */
  anchoring?: string;
  instruction?: string;
  /** A PDF cannot be edited: the cards are recommendations, with nothing to accept or export. */
  read_only?: boolean;
};

const EDITS_PAGE = 20;

export function EditProposalsCard({
  group,
  sessionId,
  messageId,
  onView,
  onFileReady,
}: {
  group: EditGroup;
  sessionId?: string;
  messageId?: string;
  onView: (edit: EditProposal) => void;
  onFileReady: (file: { document_id: string; filename: string }) => void;
}) {
  const [edits, setEdits] = useState(group.edits);
  const [busy, setBusy] = useState<string | null>(null);
  const [exporting, setExporting] = useState(false);
  const [shown, setShown] = useState(EDITS_PAGE);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const canSave = Boolean(sessionId && messageId);
  const accepted = edits.filter((e) => e.status === "accepted").length;
  const applied = edits.filter((e) => e.applied_version_id).length;
  // A PDF cannot be changed in place: its suggestions are recommendations, offered as comments.
  const readOnly = Boolean(group.read_only) || group.filename.toLowerCase().endsWith(".pdf");

  /** The document just changed: anything showing it (viewer, history, search) reloads. */
  const documentChanged = (versionNumber: number | null | undefined, count: number) => {
    void queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(group.document_id) });
    toast.success(
      `${count} edit${count === 1 ? "" : "s"} written into the document${versionNumber ? ` as version ${versionNumber}` : ""}.`,
      { action: { label: "History", onClick: () => navigate(`/documents/${encodeURIComponent(group.document_id)}?panel=versions`) } },
    );
  };

  const isPdf = readOnly;
  const [commenting, setCommenting] = useState(false);
  const [commented, setCommented] = useState(0);
  const addAsComments = async () => {
    setCommenting(true);
    let done = 0;
    try {
      for (const edit of edits) {
        if (!edit.original) continue;
        const what = edit.proposed ? `Suggested wording: ${edit.proposed}` : "Suggest deleting this passage.";
        await addComment(group.document_id, {
          body: `${what}${edit.reason ? `\n${edit.reason}` : ""}`,
          page: edit.page ?? 1,
          rects: [],
          quote: edit.original,
        });
        done += 1;
      }
      setCommented(done);
      toast.success(`${done} comment${done === 1 ? "" : "s"} added to ${group.filename}`);
    } catch (err) {
      toast.error(errorText(err, "Could not add the comments."));
    } finally {
      setCommenting(false);
    }
  };

  const decideAll = async (status: EditProposal["status"]) => {
    if (!canSave) {
      toast.info("Wait for the answer to finish before reviewing edits.");
      return;
    }
    const previous = edits;
    if (status !== "accepted") setEdits((list) => list.map((e) => (e.applied_version_id ? e : { ...e, status })));
    setBusy("all");
    try {
      const out = await decideAllEdits(sessionId!, messageId!, group.document_id, status);
      if (out.edits?.length) setEdits(out.edits);
      if (status === "accepted") {
        const failed = Object.keys(out.failed ?? {}).length;
        const wrote = out.version_number ? out.edits.filter((e) => e.applied_version_number === out.version_number).length : 0;
        if (wrote) documentChanged(out.version_number, wrote);
        if (failed) toast.error(`${failed} edit${failed === 1 ? "" : "s"} could not be placed in the document: ${Object.values(out.failed)[0]}.`);
      }
    } catch (err) {
      setEdits(previous);
      toast.error(errorText(err, "Could not save your decision."));
    } finally {
      setBusy(null);
    }
  };

  const decide = async (edit: EditProposal, status: EditProposal["status"]) => {
    if (!canSave) {
      toast.info("Wait for the answer to finish before reviewing edits.");
      return;
    }
    const previous = edits;
    if (status !== "accepted" || readOnly) setEdits((list) => list.map((e) => (e.id === edit.id ? { ...e, status } : e)));
    setBusy(edit.id);
    try {
      const saved = await decideEdit(sessionId!, messageId!, edit.id, status);
      setEdits((list) => list.map((e) => (e.id === edit.id ? { ...e, ...saved } : e)));
      if (status === "accepted" && saved.applied_version_id && !edit.applied_version_id) documentChanged(saved.applied_version_number, 1);
    } catch (err) {
      setEdits(previous);
      toast.error(errorText(err, "Could not save your decision."));
    } finally {
      setBusy(null);
    }
  };

  const exportDocx = async () => {
    setExporting(true);
    try {
      const out = await exportEdits(sessionId!, messageId!, group.document_id);
      toast.success(
        out.redline
          ? `Redline of ${out.applied} edit${out.applied === 1 ? "" : "s"} ready to download.`
          : out.tracked_in_original
          ? `${out.applied} edit${out.applied === 1 ? "" : "s"} written into the original Word file as tracked changes` +
              (out.version_label ? `; saved as version ${out.version_label} (developing).` : ".")
          : `${out.applied} edit${out.applied === 1 ? "" : "s"} saved as tracked changes.`,
      );
      onFileReady({ document_id: out.document_id, filename: out.filename });
    } catch (err) {
      toast.error(errorText(err, "Could not build the Word file."));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="mb-3 rounded-lg border border-border" data-testid="edit-proposals">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-secondary/40 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-ink">
          <PencilLine className="h-3.5 w-3.5 shrink-0 text-wine" />
          <span className="truncate">{readOnly ? "Recommendations" : "Suggested edits"} · {group.filename}</span>
          <span className="shrink-0 font-normal text-muted-foreground">({edits.length})</span>
        </div>
        {edits.length > 1 && !isPdf && (
          <div className="ml-auto flex shrink-0 items-center gap-1">
            <button type="button" disabled={busy === "all"} onClick={() => void decideAll("accepted")}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-secondary" data-testid="edits-accept-all">
              Accept all
            </button>
            <button type="button" disabled={busy === "all"} onClick={() => void decideAll("rejected")}
              className="rounded-md border border-border px-2 py-0.5 text-xs hover:bg-secondary" data-testid="edits-reject-all">
              Reject all
            </button>
          </div>
        )}
        {!isPdf && <button
          type="button"
          disabled={!canSave || accepted === 0 || exporting}
          onClick={() => void exportDocx()}
          data-testid="edits-export"
          className="inline-flex shrink-0 items-center gap-1 rounded-md bg-primary px-2 py-1 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40"
        >
          {exporting ? <Loader2 className="h-3 w-3 animate-spin" /> : <Download className="h-3 w-3" />}
          {applied > 0 && applied === accepted ? `Redline (.docx)` : `Word file (${accepted})`}
        </button>}
      </div>
      {isPdf && (
        <div className="flex flex-wrap items-center gap-2 border-b border-border bg-warning-soft px-3 py-2 text-xs text-warning-ink" data-testid="edits-pdf-note">
          <span className="min-w-0 flex-1">This is a PDF. It cannot be changed in place, so accepting these edits would change nothing.</span>
          {commented > 0 ? (
            <Link
              to={`/documents/${encodeURIComponent(group.document_id)}?panel=comments`}
              className="shrink-0 rounded-md border border-border bg-card px-2 py-1 font-medium text-foreground hover:bg-secondary"
            >
              {commented} comments added. Open
            </Link>
          ) : (
            <button
              type="button"
              disabled={commenting}
              onClick={() => void addAsComments()}
              data-testid="edits-as-comments"
              className="shrink-0 rounded-md bg-primary px-2 py-1 font-semibold text-primary-foreground disabled:opacity-50"
            >
              {commenting ? "Adding…" : "Add as comments"}
            </button>
          )}
        </div>
      )}
      <ul className="divide-y divide-border">
        {edits.slice(0, shown).map((edit, i) => (
          <li key={edit.id} className="space-y-1.5 px-3 py-2.5" data-testid="edit-card" data-status={edit.status}>
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {readOnly ? "Recommendation" : "Edit"} {i + 1}
                {edit.page ? ` · page ${edit.page}` : ""}
                {!edit.located && <span className="ml-1 text-warning-ink">· passage not found in document</span>}
              </span>
              {edit.status !== "pending" && (
                <span className={cn("font-semibold", edit.status === "accepted" ? "text-success-ink" : "text-muted-foreground")}
                  data-testid="edit-status">
                  {edit.applied_version_id ? `In the document · v${edit.applied_version_number}` : edit.status === "accepted" ? "Accepted" : "Rejected"}
                </span>
              )}
            </div>
            {edit.original && !edit.applied_version_id && (
              <p className="rounded bg-destructive/10 px-2 py-1 text-[12.5px] text-destructive line-through decoration-destructive/60">
                {edit.original}
              </p>
            )}
            {edit.proposed ? (
              <p className="rounded bg-success-soft px-2 py-1 text-[12.5px] text-success-ink">{edit.proposed}</p>
            ) : (
              <p className="text-xs italic text-muted-foreground">Delete this passage.</p>
            )}
            {edit.reason && <p className="text-[12px] text-muted-foreground">{edit.reason}</p>}
            {edit.apply_error && !edit.applied_version_id && (
              <p className="text-[12px] text-warning-ink" data-testid="edit-apply-error">
                Not applied: {edit.apply_error}.
              </p>
            )}
            <div className="flex flex-wrap items-center gap-1.5 pt-0.5">
              {!readOnly && <button
                type="button"
                disabled={busy === edit.id || Boolean(edit.applied_version_id)}
                onClick={() => void decide(edit, edit.status === "accepted" ? "pending" : "accepted")}
                data-testid="edit-accept"
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
                  edit.status === "accepted"
                    ? "border-success/40 bg-success text-white"
                    : "border-border hover:bg-secondary",
                )}
              >
                <Check className="h-3 w-3" /> Accept
              </button>}
              {!readOnly && <button
                type="button"
                disabled={busy === edit.id || Boolean(edit.applied_version_id)}
                title={edit.applied_version_id ? "Already in the document; restore an earlier version from History to undo it" : undefined}
                onClick={() => void decide(edit, edit.status === "rejected" ? "pending" : "rejected")}
                data-testid="edit-reject"
                className={cn(
                  "inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium",
                  edit.status === "rejected" ? "border-border bg-secondary text-foreground" : "border-border hover:bg-secondary",
                )}
              >
                <X className="h-3 w-3" /> Reject
              </button>}
              {edit.located && (
                <button
                  type="button"
                  onClick={() => onView(edit)}
                  data-testid="edit-view"
                  className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
                >
                  <Eye className="h-3 w-3" /> Show in document
                </button>
              )}
            </div>
          </li>
        ))}
      </ul>
      {edits.length > shown && (
        <button type="button" onClick={() => setShown((n) => n + EDITS_PAGE)} data-testid="edits-more"
          className="w-full border-t border-border py-2 text-xs text-muted-foreground hover:text-foreground">
          Show {Math.min(EDITS_PAGE, edits.length - shown)} more of {edits.length - shown}
        </button>
      )}
    </div>
  );
}

// ── generated file ────────────────────────────────────────────────────────────

export async function downloadFile(documentId: string, filename: string) {
  const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/download`, { headers: authHeaders() });
  if (!res.ok) {
    toast.error("The file is not available.");
    return;
  }
  const url = URL.createObjectURL(await res.blob());
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 5000);
}

export function FileCard({ documentId, filename, onOpen }: { documentId: string; filename: string; onOpen: () => void }) {
  return (
    <div className="mb-3 flex items-center gap-3 rounded-lg border border-border bg-secondary/30 px-3 py-2" data-testid="generated-file">
      <FileText className="h-5 w-5 shrink-0 text-wine" />
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-ink">{filename}</span>
      <button type="button" onClick={onOpen} className="rounded-md px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground">
        Open
      </button>
      <button
        type="button"
        onClick={() => void downloadFile(documentId, filename)}
        className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:bg-secondary"
      >
        <Download className="h-3 w-3" /> Download
      </button>
    </div>
  );
}

// ── comments the Assistant left ───────────────────────────────────────────────

export type CommentsAddedEvent = {
  document_id: string;
  filename: string;
  comments: { comment_id: string; quote: string; body: string; page?: number | null }[];
};

export function CommentsAddedCard({ event }: { event: CommentsAddedEvent }) {
  const [open, setOpen] = useState(false);
  const shown = open ? event.comments : event.comments.slice(0, 3);
  return (
    <div className="mb-3 rounded-lg border border-border" data-testid="comments-added">
      <div className="flex items-center justify-between gap-2 border-b border-border bg-secondary/40 px-3 py-2">
        <div className="flex min-w-0 items-center gap-1.5 text-xs font-semibold text-ink">
          <Icon name="add_comment" className="text-wine" style={{ fontSize: 16 }} />
          <span className="truncate">
            {event.comments.length} comment{event.comments.length === 1 ? "" : "s"} added to {event.filename}
          </span>
        </div>
        <Link
          to={`/documents/${encodeURIComponent(event.document_id)}?panel=comments&comment=${encodeURIComponent(event.comments[0]?.comment_id ?? "")}`}
          className="shrink-0 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:bg-secondary"
          data-testid="comments-added-open"
        >
          Open on the document
        </Link>
      </div>
      <ul className="divide-y divide-border">
        {shown.map((c) => (
          <li key={c.comment_id} className="px-3 py-2 text-sm">
            <p className="line-clamp-2 border-l-2 border-warning/60 pl-2 text-xs italic text-muted-foreground">“{c.quote}”</p>
            <p className="mt-1">{c.body}</p>
          </li>
        ))}
      </ul>
      {event.comments.length > 3 && (
        <button type="button" onClick={() => setOpen((v) => !v)} className="w-full border-t border-border py-2 text-xs text-muted-foreground hover:text-foreground">
          {open ? "Show fewer" : `Show all ${event.comments.length}`}
        </button>
      )}
    </div>
  );
}
