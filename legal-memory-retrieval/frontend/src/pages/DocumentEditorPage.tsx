import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { EditorContent, Extension, useEditor, useEditorState, type Editor, type JSONContent } from "@tiptap/react";
import { Plugin } from "@tiptap/pm/state";
import type { Node as PMNode } from "@tiptap/pm/model";
import StarterKit from "@tiptap/starter-kit";
import Paragraph from "@tiptap/extension-paragraph";
import {
  acquireLock,
  deleteDraft,
  editConflict,
  editErrorMessage,
  forgetLock,
  getEditModel,
  heartbeatLock,
  putDraft,
  releaseLock,
  releaseLockOnUnload,
  saveEdits,
  type EditLock,
  type EditModel,
  type EditOp,
  type EditParagraph,
  type EditRun,
  downloadWithCommentsUrl,
  type LockConflictReason,
} from "@/api/editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { EmptyState, Icon, MonoId } from "@/components/common/primitives";
import { ExactView } from "@/components/editor/ExactView";
import { PrivacyControl } from "@/components/editor/PrivacyControl";
import { UploadVersionDialog } from "@/components/editor/UploadVersionDialog";
import { useApp } from "@/context/AppContext";
import { applyOps, computeOps, mergeRuns, wordDiff, type LivePara } from "@/lib/editorOps";
import { cn } from "@/lib/utils";
import { authHeaders } from "@/api/client";


const HEARTBEAT_MS = 90 * 1000; // lock TTL is 5 min on the server
const AUTOSAVE_MS = 2000;

/** Paragraph that remembers which original Word paragraph it came from. */
const DocParagraph = Paragraph.extend({
  addAttributes() {
    return {
      pid: {
        default: null,
        keepOnSplit: false,
        parseHTML: (el: HTMLElement) => (el.getAttribute("data-pid") ? Number(el.getAttribute("data-pid")) : null),
        renderHTML: (attrs: { pid: number | null }) => (attrs.pid === null ? {} : { "data-pid": String(attrs.pid) }),
      },
      pstyle: {
        default: "Normal",
        keepOnSplit: false,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-style") || "Normal",
        renderHTML: (attrs: { pstyle: string }) => ({ "data-style": attrs.pstyle, class: styleClass(attrs.pstyle) }),
      },
      // Pending tracked changes by other reviewers: shown, not editable until reviewed.
      locked: {
        default: null,
        keepOnSplit: false,
        parseHTML: (el: HTMLElement) => el.getAttribute("data-locked-by"),
        renderHTML: (attrs: { locked: string | null }) =>
          attrs.locked ? { "data-locked-by": attrs.locked, "data-testid": "editor-locked-para", title: attrs.locked } : {},
      },
    };
  },
});

/** Locked paragraphs by pid (top-level nodes). */
function lockedNodes(doc: PMNode) {
  const out = new Map<number, PMNode>();
  doc.forEach((n) => {
    if (n.attrs.locked && n.attrs.pid !== null) out.set(n.attrs.pid as number, n);
  });
  return out;
}

/** Refuses any edit that would change a locked paragraph (typing in it, deleting it, merging into it). */
const LockGuard = Extension.create<{ onBlocked: () => void }>({
  name: "lockGuard",
  addOptions() {
    return { onBlocked: () => undefined };
  },
  addProseMirrorPlugins() {
    const onBlocked = this.options.onBlocked;
    return [
      new Plugin({
        filterTransaction(tr, state) {
          if (!tr.docChanged) return true;
          const before = lockedNodes(state.doc);
          if (!before.size) return true;
          const after = lockedNodes(tr.doc);
          for (const [pid, node] of before) {
            const now = after.get(pid);
            if (!now || !(now === node || now.eq(node))) {
              onBlocked();
              return false;
            }
          }
          return true;
        },
      }),
    ];
  },
});

function lockLabel(p: EditParagraph): string | null {
  if (!p.locked) return null;
  if (p.locked_reason === "deleted") return "Deletion pending — review it first";
  const names = [...new Set((p.pending ?? []).map((x) => x.author))];
  return `Pending changes by ${names.join(", ")} — review them first`;
}

function styleClass(style: string): string {
  const s = style.toLowerCase();
  if (s === "title") return "doc-title";
  if (s.startsWith("heading 1")) return "doc-h1";
  if (s.startsWith("heading")) return "doc-h2";
  return "doc-p";
}

type EditorPara = EditParagraph & { pidLive?: number | null };

function toContent(paras: EditorPara[]): JSONContent {
  return {
    type: "doc",
    content: paras.map((p) => ({
      type: "paragraph",
      attrs: { pid: p.pidLive === undefined ? p.pid : p.pidLive, pstyle: p.style, locked: lockLabel(p) },
      content: p.runs
        .filter((r) => r.text)
        .map((r) => {
          const marks: { type: string }[] = [];
          if (r.bold) marks.push({ type: "bold" });
          if (r.italic) marks.push({ type: "italic" });
          if (r.underline) marks.push({ type: "underline" });
          return { type: "text", text: r.text.replace(/\n/g, " "), marks };
        }),
    })),
  };
}

function readLive(editor: Editor): LivePara[] {
  const out: LivePara[] = [];
  editor.state.doc.forEach((node) => {
    const runs: EditRun[] = [];
    node.forEach((child) => {
      if (!child.isText || !child.text) return;
      const has = (name: string) => child.marks.some((m) => m.type.name === name);
      runs.push({ text: child.text, bold: has("bold"), italic: has("italic"), underline: has("underline") });
    });
    out.push({
      pid: (node.attrs.pid as number | null) ?? null,
      text: node.textContent,
      style: (node.attrs.pstyle as string) || "Normal",
      runs: mergeRuns(runs),
    });
  });
  return out;
}

/**
 * Take the page's current selection into the editor state. The editor learns about a mouse
 * selection asynchronously; a toolbar control that takes focus straight after a click must
 * not act on the previous selection.
 */
function syncSelection(editor: Editor | null) {
  const sel = window.getSelection();
  if (!editor || !sel?.anchorNode || !editor.view.dom.contains(sel.anchorNode)) return;
  try {
    const a = editor.view.posAtDOM(sel.anchorNode, sel.anchorOffset);
    const b = sel.focusNode && editor.view.dom.contains(sel.focusNode) ? editor.view.posAtDOM(sel.focusNode, sel.focusOffset) : a;
    editor.commands.setTextSelection({ from: Math.min(a, b), to: Math.max(a, b) });
  } catch {
    // a position outside the text (e.g. between nodes): keep the editor's own selection
  }
}

/** "Bold added", "Italic removed", … between two formattings of the same text. */
function formattingSummary(before: EditRun[], after: EditRun[]): string[] {
  const flags = (runs: EditRun[], key: "bold" | "italic" | "underline") => runs.flatMap((r) => Array.from(r.text, () => r[key]));
  const out: string[] = [];
  for (const [key, label] of [["bold", "Bold"], ["italic", "Italic"], ["underline", "Underline"]] as const) {
    const a = flags(before, key);
    const b = flags(after, key);
    if (a.length !== b.length) continue;
    if (b.some((v, i) => v && !a[i])) out.push(`${label} added`);
    if (a.some((v, i) => v && !b[i])) out.push(`${label} removed`);
  }
  return out;
}

export function DocumentEditorPage() {
  const { id = "" } = useParams();
  const { identityKey } = useApp();
  const model = useQuery({
    queryKey: [identityKey, "edit-model", id],
    queryFn: () => getEditModel(id),
    enabled: !!id && identityKey !== null,
    staleTime: Infinity,
    retry: false,
  });
  if (model.isPending) return <p className="p-8 text-sm text-muted-foreground">Opening the document…</p>;
  if (model.isError || !model.data) {
    return <EmptyState icon="search_off" title="Document not found" description="It does not exist or is outside your access scope." />;
  }
  return <EditorWorkspace key={model.data.base_version_id} model={model.data} />;
}

function EditorWorkspace({ model }: { model: EditModel }) {
  const id = model.document_id;
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { identityKey, toast } = useApp();
  const [searchParams, setSearchParams] = useSearchParams();
  const [view, setView] = useState<"edit" | "exact" | "review">(() => {
    const asked = searchParams.get("view");
    if (asked === "review" && model.mode === "docx") return "review";
    if (asked === "exact") return "exact";
    return model.mode === "pdf" ? "exact" : "edit";
  });
  const [blocked, setBlocked] = useState(false);
  const [lock, setLock] = useState<LockState>({ mine: false, holder: model.lock });
  const [ops, setOps] = useState<EditOp[]>([]);
  const [unplaced, setUnplaced] = useState<string[]>([]);
  const [draftState, setDraftState] = useState<"idle" | "saving" | "saved" | "error">("idle");
  const [restore, setRestore] = useState(
    Boolean(model.draft && model.draft.base_version_id === model.base_version_id && model.draft.ops.length),
  );
  const [saveOpen, setSaveOpen] = useState(false);
  const [uploadOpen, setUploadOpen] = useState(false);
  const snapshot = useRef<EditParagraph[]>([]);
  const autosave = useRef<number | null>(null);

  const canEdit = model.editable && model.mode !== "pdf" && lock.mine;

  const editor = useEditor({
    extensions: [
      StarterKit.configure({
        paragraph: false,
        heading: false,
        bulletList: false,
        orderedList: false,
        listItem: false,
        codeBlock: false,
        code: false,
        blockquote: false,
        horizontalRule: false,
        strike: false,
        link: false,
      }),
      DocParagraph,
      LockGuard.configure({ onBlocked: () => setBlocked(true) }),
    ],
    content: toContent(model.paragraphs),
    editable: false,
    immediatelyRender: false,
    editorProps: { attributes: { class: "doc-page-body focus:outline-none", "data-testid": "editor-body", spellcheck: "true" } },
    onCreate: ({ editor: ed }) => {
      // The basis is what the editor shows before any edit (line breaks normalised), so an
      // untouched paragraph never counts as changed.
      snapshot.current = readLive(ed).map((p, i) => ({ pid: model.paragraphs[i].pid, style: p.style, text: p.text, runs: p.runs }));
    },
    onUpdate: ({ editor: ed }) => {
      const { ops: next, unplaced: stray } = computeOps(snapshot.current, readLive(ed), model.styles);
      setOps(next);
      setUnplaced(stray);
      scheduleAutosave(next);
    },
  });

  // ── lock ──────────────────────────────────────────────────────────────────
  // One window edits at a time. Another window (or person) sees why it cannot edit and,
  // when allowed, can take over; the window that loses the lock stops writing and keeps
  // what it had as the person's draft.
  const beat = useRef<number | null>(null);
  const stopBeat = () => {
    if (beat.current) window.clearInterval(beat.current);
    beat.current = null;
  };
  const takeLock = useCallback(
    (takeover: boolean) => {
      if (!model.editable || model.mode === "pdf") return Promise.resolve();
      return acquireLock(id, { takeover })
        .then((mine) => {
          setLock({ mine: true, holder: mine });
          stopBeat();
          beat.current = window.setInterval(() => {
            heartbeatLock(id).catch((err) => {
              const c = editConflict(err);
              stopBeat();
              forgetLock(id);
              setLock({ mine: false, holder: c?.lock ?? null, reason: "superseded" });
              toast(editErrorMessage(err));
            });
          }, HEARTBEAT_MS);
        })
        .catch((err) => {
          const c = editConflict(err);
          setLock({ mine: false, holder: c?.lock ?? null, reason: c?.reason, canTakeOver: c?.can_take_over });
          if (takeover) toast(editErrorMessage(err));
        });
    },
    [id, model.editable, model.mode, toast],
  );

  useEffect(() => {
    if (!model.editable || model.mode === "pdf") return;
    void takeLock(false);
    const unload = () => releaseLockOnUnload(id);
    window.addEventListener("pagehide", unload);
    return () => {
      stopBeat();
      window.removeEventListener("pagehide", unload);
      void releaseLock(id).catch(() => undefined);
    };
  }, [id, model.editable, model.mode, takeLock]);

  useEffect(() => {
    editor?.setEditable(canEdit && !restore);
  }, [editor, canEdit, restore]);

  // ── autosave ──────────────────────────────────────────────────────────────
  const scheduleAutosave = useCallback(
    (next: EditOp[]) => {
      if (autosave.current) window.clearTimeout(autosave.current);
      autosave.current = window.setTimeout(() => {
        setDraftState("saving");
        const job = next.length ? putDraft(id, model.base_version_id, next) : deleteDraft(id);
        job.then(() => setDraftState("saved")).catch((err) => {
          setDraftState("error");
          // Another window took over: stop editing here now rather than at the next heartbeat.
          const c = editConflict(err);
          if (c?.reason === "superseded") {
            stopBeat();
            forgetLock(id);
            setLock({ mine: false, holder: c.lock ?? null, reason: "superseded" });
          }
        });
      }, AUTOSAVE_MS);
    },
    [id, model.base_version_id],
  );

  useEffect(() => () => {
    if (autosave.current) window.clearTimeout(autosave.current);
  }, []);

  const restoreDraft = () => {
    if (!editor || !model.draft) return;
    editor.commands.setContent(toContent(applyOps(model.paragraphs, model.draft.ops)), { emitUpdate: true });
    setRestore(false);
  };
  const discardDraft = () => {
    void deleteDraft(id).catch(() => undefined);
    setRestore(false);
  };

  // Ctrl/Cmd+S opens the save dialog.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "s") {
        e.preventDefault();
        if (ops.length && canEdit) setSaveOpen(true);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [ops.length, canEdit]);

  const afterNewVersion = (versionNumber: number) => {
    // Leave first: refreshing while still here would remount the editor on the new
    // version and take the edit lock again just before navigating away.
    navigate(`/documents/${encodeURIComponent(id)}?panel=versions`);
    toast(`Saved as version ${versionNumber}`);
    void queryClient.invalidateQueries({ queryKey: [identityKey] });
  };

  // After accept/reject: stay in Review on the new version (the page reloads onto it).
  const afterReview = (versionNumber: number, note: string) => {
    toast(`${note} — saved as version ${versionNumber}`);
    setSearchParams({ view: "review" }, { replace: true });
    void queryClient.invalidateQueries({ queryKey: [identityKey] });
  };

  const downloadWithComments = async () => {
    const res = await fetch(downloadWithCommentsUrl(id), { headers: authHeaders(), credentials: "same-origin" });
    if (!res.ok) return toast("Could not prepare the file");
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = `${model.title.replace(/\.docx$/i, "")}.docx`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const changed = useMemo(() => {
    const base = new Map(snapshot.current.map((p) => [p.pid, p]));
    return ops.map((op) => {
      const orig = op.op === "insert_after" ? undefined : base.get(op.pid);
      const notes: string[] = [];
      if ((op.op === "replace" || op.op === "format") && orig) {
        if (op.style && op.style !== orig.style) notes.push(`Style → ${op.style}`);
        if (op.op === "format" && op.runs) notes.push(...formattingSummary(orig.runs, op.runs));
      }
      if (op.op === "insert_after" && op.style && op.style !== "Normal") notes.push(`Style: ${op.style}`);
      return { op, before: orig?.text ?? "", notes };
    });
  }, [ops]);

  // Toolbar state follows the selection.
  const fmt = useEditorState({
    editor,
    selector: ({ editor: ed }) => ({
      bold: ed?.isActive("bold") ?? false,
      italic: ed?.isActive("italic") ?? false,
      underline: ed?.isActive("underline") ?? false,
      style: (ed?.getAttributes("paragraph").pstyle as string | undefined) ?? "Normal",
      canUndo: ed?.can().undo() ?? false,
      canRedo: ed?.can().redo() ?? false,
    }),
  });

  return (
    <div className="flex h-full min-h-0 flex-col overflow-y-auto bg-secondary/40" data-testid="document-editor">
      {/* header */}
      <div className="sticky top-0 z-20 border-b border-border bg-background/95 px-6 py-3 backdrop-blur">
        <div className="flex flex-wrap items-center gap-3">
          <Link to={`/documents/${encodeURIComponent(id)}`} className="text-muted-foreground hover:text-foreground" aria-label="Back to document">
            <Icon name="arrow_back" />
          </Link>
          <div className="min-w-0 flex-1">
            <div className="truncate font-display text-lg text-ink" data-testid="editor-title">{model.title}</div>
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <MonoId>{id}</MonoId>
              <span>· editing v{model.version_number ?? "?"}</span>
              {(model.pending_changes ?? 0) > 0 && (
                <button type="button" onClick={() => setView("review")} className="rounded bg-amber-100 px-1.5 text-amber-900 hover:underline"
                  data-testid="editor-pending-chip">
                  {model.pending_changes} pending change{model.pending_changes === 1 ? "" : "s"} by {model.pending_people?.join(", ")}
                </button>
              )}
              <DraftBadge state={draftState} pending={ops.length} />
              <PrivacyControl documentId={id} />
            </div>
          </div>
          <div className="flex rounded-md border border-border p-0.5" role="tablist" aria-label="View">
            {model.mode !== "pdf" && (
              <button type="button" role="tab" aria-selected={view === "edit"} onClick={() => setView("edit")}
                className={cn("rounded px-3 py-1 text-sm", view === "edit" ? "bg-wine-soft font-medium text-wine" : "text-muted-foreground")}
                data-testid="editor-view-edit">
                Edit
              </button>
            )}
            <button type="button" role="tab" aria-selected={view === "exact"} onClick={() => setView("exact")}
              className={cn("rounded px-3 py-1 text-sm", view === "exact" ? "bg-wine-soft font-medium text-wine" : "text-muted-foreground")}
              data-testid="editor-view-exact">
              Exact view
            </button>
            {model.mode === "docx" && (
              <button type="button" role="tab" aria-selected={view === "review"} onClick={() => setView("review")}
                className={cn("rounded px-3 py-1 text-sm", view === "review" ? "bg-wine-soft font-medium text-wine" : "text-muted-foreground")}
                data-testid="editor-view-review">
                Review
              </button>
            )}
          </div>
          {model.mode === "docx" && (
            <Button variant="outline" size="sm" onClick={() => void downloadWithComments()} data-testid="editor-download-comments"
              title="The Word file with every comment and reply made here">
              <Icon name="download" style={{ fontSize: 16 }} /> Word file with comments
            </Button>
          )}
          {model.editable && (
            <Button variant="outline" size="sm" onClick={() => setUploadOpen(true)} data-testid="editor-upload">
              <Icon name="upload" style={{ fontSize: 16 }} /> Upload version
            </Button>
          )}
          {canEdit && (
            <Button size="sm" disabled={!ops.length || unplaced.length > 0} onClick={() => setSaveOpen(true)} data-testid="editor-save">
              Save version{ops.length ? ` (${ops.length})` : ""}
            </Button>
          )}
        </div>
        {view === "edit" && canEdit && (
          <div className="mt-2 flex items-center gap-1" data-testid="editor-toolbar">
            <ToolButton icon="undo" label="Undo" onClick={() => editor?.chain().focus().undo().run()} disabled={!fmt?.canUndo} />
            <ToolButton icon="redo" label="Redo" onClick={() => editor?.chain().focus().redo().run()} disabled={!fmt?.canRedo} />
            <span className="mx-1 h-5 w-px bg-border" />
            {model.styles.length > 0 && (
              <select
                aria-label="Paragraph style"
                value={model.styles.includes(fmt?.style ?? "") ? fmt?.style : ""}
                onMouseDown={() => syncSelection(editor)}
                onFocus={() => syncSelection(editor)}
                onChange={(e) => {
                  syncSelection(editor);
                  editor?.chain().focus().updateAttributes("paragraph", { pstyle: e.target.value }).run();
                }}
                className="h-8 rounded-md border border-border bg-background px-2 text-sm"
                data-testid="editor-style"
              >
                {!model.styles.includes(fmt?.style ?? "") && <option value="">{fmt?.style}</option>}
                {model.styles.map((st) => <option key={st} value={st}>{st}</option>)}
              </select>
            )}
            <ToolButton icon="format_bold" label="Bold (Ctrl+B)" active={fmt?.bold} onPress={() => syncSelection(editor)} onClick={() => editor?.chain().focus().toggleBold().run()} testId="editor-bold" />
            <ToolButton icon="format_italic" label="Italic (Ctrl+I)" active={fmt?.italic} onPress={() => syncSelection(editor)} onClick={() => editor?.chain().focus().toggleItalic().run()} testId="editor-italic" />
            <ToolButton icon="format_underlined" label="Underline (Ctrl+U)" active={fmt?.underline} onPress={() => syncSelection(editor)} onClick={() => editor?.chain().focus().toggleUnderline().run()} testId="editor-underline" />
            <span className="ml-3 text-xs text-muted-foreground">
              Text and formatting changes are saved into the original Word file as tracked changes under your name; everything you do not touch keeps its formatting.
            </span>
          </div>
        )}
      </div>

      {/* banners */}
      <div className="space-y-2 px-6 pt-4">
        {!model.editable && model.mode !== "pdf" && <Banner icon="visibility">You can read this document but not edit it.</Banner>}
        {model.mode === "pdf" && (
          <Banner icon="picture_as_pdf">PDFs cannot be edited in the browser. Upload a Word version to edit the text; comments and highlights stay in the viewer.</Banner>
        )}
        {model.editable && model.mode !== "pdf" && !lock.mine && (
          <Banner icon="lock" testId="editor-locked">
            {lockMessage(lock)}
            {(lock.reason === "held_by_you_elsewhere" || lock.canTakeOver) && (
              <Button size="sm" className="ml-3" onClick={() => void takeLock(true)} data-testid="editor-take-over">
                {lock.reason === "held_by_you_elsewhere" ? "Edit here instead" : "Take over editing"}
              </Button>
            )}
            {lock.reason === "superseded" && (
              <Button size="sm" variant="outline" className="ml-3" onClick={() => window.location.reload()}>Reload</Button>
            )}
          </Banner>
        )}
        {restore && canEdit && (
          <Banner icon="history" testId="editor-draft-banner">
            You have unsaved changes from {model.draft ? new Date(model.draft.updated_at).toLocaleString() : "earlier"} ({model.draft?.ops.length} edits).
            <Button size="sm" className="ml-3" onClick={restoreDraft} data-testid="editor-draft-restore">Restore</Button>
            <Button size="sm" variant="outline" className="ml-2" onClick={discardDraft}>Discard</Button>
          </Banner>
        )}
        {blocked && view === "edit" && (
          <Banner icon="rate_review" testId="editor-blocked">
            That paragraph has tracked changes by other reviewers. Accept or reject them in Review first; everything else stays editable.
            <Button size="sm" className="ml-3" onClick={() => { setBlocked(false); setView("review"); }}>Open Review</Button>
            <Button size="sm" variant="outline" className="ml-2" onClick={() => setBlocked(false)}>OK</Button>
          </Banner>
        )}
        {unplaced.length > 0 && (
          <Banner icon="warning">New text above the first paragraph cannot be placed; type it below the title instead.</Banner>
        )}
      </div>

      {/* body */}
      {view === "exact" && <ExactView documentId={id} currentVersionId={model.base_version_id} showViews={Boolean(model.pending_changes)} />}
      {view === "review" && (
        <ExactView documentId={id} currentVersionId={model.base_version_id} showViews
          side={{ kind: "review", baseVersionId: model.base_version_id, canWrite: canEdit, onNewVersion: afterReview }} />
      )}
      <div className={cn("grid flex-1 gap-6 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_320px]", view !== "edit" && "hidden")}>
        <div className="min-w-0">
          <div className="mx-auto w-full max-w-[816px] rounded-sm bg-card px-12 py-14 shadow-md ring-1 ring-border lg:px-[72px]" data-testid="editor-page">
            <EditorContent editor={editor} />
          </div>
        </div>
        <aside className="space-y-4" data-testid="editor-changes">
          <div className="rounded-lg border border-border bg-card p-4">
            <div className="mb-2 flex items-center justify-between">
              <span className="text-sm font-semibold">Your changes</span>
              <span className="text-xs text-muted-foreground">{ops.length}</span>
            </div>
            {ops.length === 0 ? (
              <p className="text-xs text-muted-foreground">Nothing changed yet.</p>
            ) : (
              <ul className="max-h-[60vh] space-y-3 overflow-y-auto">
                {changed.map(({ op, before, notes }, i) => (
                  <li key={i} className="text-xs leading-relaxed">
                    <div className="mb-0.5 font-semibold uppercase tracking-wide text-muted-foreground">
                      {op.op === "replace" ? "Changed" : op.op === "delete" ? "Deleted" : op.op === "format" ? "Formatted" : "Added"}
                    </div>
                    {notes.length > 0 && <div className="mb-0.5 text-muted-foreground" data-testid="editor-change-notes">{notes.join(" · ")}</div>}
                    {op.op === "format" && <span className="line-clamp-2">{before}</span>}
                    {op.op === "replace" && <DiffText before={before} after={op.text} />}
                    {op.op === "delete" && <del className="text-destructive">{before}</del>}
                    {op.op === "insert_after" && <ins className="text-success no-underline">{op.text}</ins>}
                  </li>
                ))}
              </ul>
            )}
          </div>
        </aside>
      </div>

      <SaveDialog
        open={saveOpen}
        onOpenChange={setSaveOpen}
        count={ops.length}
        onSave={async (note, mode) => {
          const r = await saveEdits(id, { base_version_id: model.base_version_id, ops, note, mode });
          afterNewVersion(r.version_number);
        }}
      />
      <UploadVersionDialog
        documentId={id}
        baseVersionId={model.base_version_id}
        versionNumber={model.version_number}
        open={uploadOpen}
        onOpenChange={setUploadOpen}
        onUploaded={(v) => afterNewVersion(v.version_number)}
      />
    </div>
  );
}

type LockState = { mine: boolean; holder: EditLock | null; reason?: LockConflictReason; canTakeOver?: boolean };

function lockMessage(lock: LockState): string {
  if (lock.reason === "held_by_you_elsewhere") return "You are editing this document in another window.";
  if (lock.reason === "superseded")
    return `${lock.holder ? `${lock.holder.name} took over editing` : "Your editing session ended"}. Your changes are kept as your draft.`;
  if (lock.holder) return `${lock.holder.name} is editing this document. You can read it; editing opens when they finish.`;
  return "Opening the editor…";
}

function DraftBadge({ state, pending }: { state: string; pending: number }) {
  if (!pending && state === "idle") return null;
  const text = state === "saving" ? "saving draft…" : state === "saved" ? "draft saved" : state === "error" ? "draft not saved" : "unsaved";
  return <span className={cn("· ", state === "error" && "text-destructive")} data-testid="editor-draft-state">· {text}</span>;
}

function DiffText({ before, after }: { before: string; after: string }) {
  return (
    <span>
      {wordDiff(before, after).map((s, i) =>
        s.t === "eq" ? <span key={i} className="text-muted-foreground">{s.text}</span>
          : s.t === "del" ? <del key={i} className="bg-destructive/10 text-destructive">{s.text}</del>
            : <ins key={i} className="bg-success/10 text-success no-underline">{s.text}</ins>,
      )}
    </span>
  );
}

function Banner({ icon, children, testId }: { icon: string; children: React.ReactNode; testId?: string }) {
  return (
    <div className="mx-auto flex max-w-[816px] items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm" data-testid={testId}>
      <Icon name={icon} className="text-wine" style={{ fontSize: 18 }} />
      <div className="flex flex-wrap items-center">{children}</div>
    </div>
  );
}

function ToolButton({ icon, label, onClick, onPress, disabled, active, testId }: {
  icon: string; label: string; onClick: () => void; onPress?: () => void; disabled?: boolean; active?: boolean; testId?: string;
}) {
  return (
    <button type="button" aria-label={label} title={label} onClick={onClick} onMouseDown={onPress} disabled={disabled} aria-pressed={active}
      data-testid={testId}
      className={cn("rounded p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-40",
        active && "bg-secondary text-foreground")}>
      <Icon name={icon} style={{ fontSize: 18 }} />
    </button>
  );
}

function SaveDialog({ open, onOpenChange, count, onSave }: {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  count: number;
  onSave: (note: string, mode: "tracked" | "clean") => Promise<void>;
}) {
  const [note, setNote] = useState("");
  const [mode, setMode] = useState<"tracked" | "clean">("tracked");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSave(note, mode);
      onOpenChange(false);
    } catch (err) {
      setError(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="editor-save-dialog">
        <DialogHeader>
          <DialogTitle>Save as a new version</DialogTitle>
          <DialogDescription>{count} change{count === 1 ? "" : "s"} will be recorded under your name.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Input placeholder="What changed and why" value={note} onChange={(e) => setNote(e.target.value)} data-testid="editor-save-note" />
          <label className="flex items-start gap-2 text-sm">
            <input type="radio" checked={mode === "tracked"} onChange={() => setMode("tracked")} className="mt-1" />
            <span><b>Track changes</b> — the Word file shows your edits as insertions and deletions for others to accept.</span>
          </label>
          <label className="flex items-start gap-2 text-sm">
            <input type="radio" checked={mode === "clean"} onChange={() => setMode("clean")} className="mt-1" />
            <span><b>Clean</b> — accept the edits; the history still shows the difference to the previous version.</span>
          </label>
          {error && <p className="text-sm text-destructive" data-testid="editor-save-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={busy} onClick={() => void submit()} data-testid="editor-save-confirm">{busy ? "Saving…" : "Save version"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
