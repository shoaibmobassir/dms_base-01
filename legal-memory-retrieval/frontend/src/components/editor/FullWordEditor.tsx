import { useCallback, useEffect, useRef, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { DocxEditor, type DocxEditorRef } from "@stll/folio-react";
import folioMessages from "@stll/folio-react/messages/en";
import "@stll/folio-react/editor.css";
import { IntlProvider } from "use-intl";
import { authHeaders } from "@/api/client";
import {
  acquireLock,
  deleteDocxDraft,
  editConflict,
  editErrorMessage,
  getDocxDraft,
  getDocxDraftInfo,
  getEditModel,
  heartbeatLock,
  putDocxDraft,
  releaseLock,
  releaseLockOnUnload,
  saveDocx,
  type EditModel,
} from "@/api/editor";
import { Icon } from "@/components/common/primitives";
import { registerWordEditor, type SuggestEdit, type SuggestResult } from "@/lib/wordEditorBridge";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

/**
 * The full Word editor (plan 22, W2b): the document as Word lays it out — tables, headers and footers, footnotes,
 * other people's tracked changes — editable in the browser. Changes are tracked by default; saving makes the next
 * version, and the server credits each new change to the signed-in person. One editor at a time (the edit lock).
 */
export function FullWordEditor({ documentId, onSaved }: { documentId: string; onSaved?: (versionNumber: number) => void }) {
  const { me, toast } = useApp();
  const queryClient = useQueryClient();
  const ref = useRef<DocxEditorRef | null>(null);
  const [model, setModel] = useState<EditModel | null>(null);
  const [buffer, setBuffer] = useState<ArrayBuffer | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [locked, setLocked] = useState<{ by: string; canTakeOver: boolean } | null>(null);
  const [mode, setMode] = useState<"suggesting" | "editing">("suggesting");
  const [saving, setSaving] = useState(false);
  const [asking, setAsking] = useState(false);
  const [note, setNote] = useState("");
  const [haveLock, setHaveLock] = useState(false);
  const [draft, setDraft] = useState<{ updated_at: string } | null>(null);
  const [savedAt, setSavedAt] = useState<string | null>(null);
  const [editorKey, setEditorKey] = useState(0);

  const load = useCallback(async () => {
    setError(null);
    try {
      const m = await getEditModel(documentId);
      setModel(m);
      if (m.mode !== "docx") {
        setError(m.mode === "pdf" ? "PDFs are not edited in the browser. Upload a Word version to edit its text." : "This document has no Word file; use the simple editor.");
        return;
      }
      const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/download?version_id=${encodeURIComponent(m.base_version_id)}`,
        { headers: authHeaders(), credentials: "same-origin" });
      if (!res.ok) throw new Error(`The Word file could not be opened (HTTP ${res.status})`);
      setBuffer(await res.arrayBuffer());
      setEditorKey((k) => k + 1);
      setDraft(null);
      if (m.editable) {
        const d = await getDocxDraftInfo(documentId).catch(() => null);
        if (d?.current) setDraft({ updated_at: d.updated_at });
      }
    } catch (err) {
      setError(editErrorMessage(err));
    }
  }, [documentId]);

  const lock = useCallback(async (takeover = false) => {
    try {
      await acquireLock(documentId, { takeover });
      setHaveLock(true);
      setLocked(null);
    } catch (err) {
      const c = editConflict(err);
      setHaveLock(false);
      setLocked({ by: c?.lock?.name ?? "someone else", canTakeOver: !!c?.can_take_over });
    }
  }, [documentId]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!model?.editable || model.mode !== "docx") return;
    void lock();
    const beat = window.setInterval(() => void heartbeatLock(documentId).catch(() => setHaveLock(false)), 90_000);
    const unload = () => releaseLockOnUnload(documentId);
    window.addEventListener("pagehide", unload);
    return () => {
      window.clearInterval(beat);
      window.removeEventListener("pagehide", unload);
      void releaseLock(documentId).catch(() => undefined);
    };
  }, [model?.editable, model?.mode, documentId, lock]);

  // Autosave: every 30 s while there are unsaved edits and this window holds the lock.
  useEffect(() => {
    if (!model?.editable || !haveLock || draft) return;
    const t = window.setInterval(async () => {
      if (!ref.current?.hasPendingChanges()) return;
      try {
        const data = await ref.current.save();
        if (data) {
          await putDocxDraft(documentId, data, model.base_version_id);
          setSavedAt(new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" }));
        }
      } catch {
        // the next tick tries again; saving a version is what matters
      }
    }, (window as unknown as { __autosaveMs?: number }).__autosaveMs ?? 30_000);
    return () => window.clearInterval(t);
  }, [model?.editable, model?.base_version_id, haveLock, draft, documentId]);

  const restoreDraft = async () => {
    try {
      setBuffer(await getDocxDraft(documentId));
      setEditorKey((k) => k + 1);
      setDraft(null);
      toast("Your unsaved changes are back. Save a version to keep them.");
    } catch (err) {
      toast(editErrorMessage(err));
    }
  };
  const discardDraft = async () => {
    await deleteDocxDraft(documentId).catch(() => undefined);
    setDraft(null);
  };

  // Leaving with unsaved edits asks first.
  useEffect(() => {
    const guard = (e: BeforeUnloadEvent) => {
      if (ref.current?.hasPendingChanges()) e.preventDefault();
    };
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, []);

  const save = async () => {
    if (!model || !ref.current) return;
    setSaving(true);
    try {
      const data = await ref.current.save();
      if (!data) throw new Error("The editor produced no file");
      const out = await saveDocx(documentId, data, { baseVersionId: model.base_version_id, note: note.trim() });
      await queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(documentId) });
      toast(`Saved as version ${out.version_number}${out.changes ? ` · ${out.changes} tracked change${out.changes === 1 ? "" : "s"} credited to you` : ""}`);
      setAsking(false);
      setNote("");
      onSaved?.(out.version_number);
      await load(); // continue on the new version
    } catch (err) {
      toast(editErrorMessage(err));
    } finally {
      setSaving(false);
    }
  };

  const readOnly = !model?.editable || !haveLock;

  // The Assistant's edit cards can hand this editor pending suggestions (accepted or rejected in the review sidebar).
  const suggest = useCallback((edits: SuggestEdit[]): SuggestResult => {
    const editor = ref.current;
    editor?.ensureEditorView({ focus: false }); // the view is created lazily; a snapshot needs it
    const snapshot = editor?.createAIEditSnapshot();
    if (!editor || !snapshot) return { suggested: 0, skipped: edits.map((e) => ({ id: e.id, reason: "The editor is not ready" })), error: "The editor is not ready" };
    const norm = (t: string) => t.replace(/\s+/g, " ").trim();
    const operations: Parameters<DocxEditorRef["applyAIEditOperations"]>[0]["operations"] = [];
    const skipped: SuggestResult["skipped"] = [];
    for (const e of edits) {
      const want = norm(e.original);
      const blocks = want ? snapshot.blocks.filter((b) => norm(b.text).includes(want)) : [];
      if (e.op === "insert_after" || !want) skipped.push({ id: e.id, reason: "New paragraphs are not suggested here" });
      else if (blocks.length !== 1) skipped.push({ id: e.id, reason: blocks.length ? "The passage appears more than once" : "The passage was not found" });
      else operations.push({ id: e.id, type: "replaceInBlock", blockId: blocks[0].id, find: e.original.trim(), replace: e.proposed });
    }
    if (!operations.length) return { suggested: 0, skipped };
    const out = editor.applyAIEditOperations({ snapshot, operations, mode: "suggested", author: "Assistant" });
    for (const sk of out.skipped ?? []) skipped.push({ id: String((sk as { id?: string }).id ?? ""), reason: String((sk as { reason?: string }).reason ?? "could not be placed") });
    return { suggested: (out.applied ?? []).length, skipped };
  }, []);
  useEffect(() => (readOnly || !buffer ? undefined : registerWordEditor(documentId, suggest)), [readOnly, buffer, documentId, suggest]);
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="full-word-editor">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card px-3 py-2">
        <Icon name="edit_document" className="text-wine" style={{ fontSize: 20 }} />
        <span className="min-w-0 truncate font-display text-lg text-ink">{model?.title ?? "Opening…"}</span>
        {model?.version_number != null && <span className="rounded-md border border-border px-2 py-0.5 text-xs">editing v{model.version_number}</span>}
        {savedAt && <span className="text-xs text-muted-foreground" data-testid="full-editor-autosaved">Draft kept at {savedAt}</span>}
        <div className="flex-1" />
        {model?.editable && (
          <div className="flex rounded-md border border-border p-0.5 text-xs" role="radiogroup" aria-label="Changes">
            {(["suggesting", "editing"] as const).map((m) => (
              <button key={m} type="button" role="radio" aria-checked={mode === m} onClick={() => setMode(m)} disabled={readOnly}
                className={cn("rounded px-2 py-1", mode === m ? "bg-secondary font-medium" : "text-muted-foreground")}>
                {m === "suggesting" ? "Track changes" : "Edit directly"}
              </button>
            ))}
          </div>
        )}
        {model?.editable && (
          <Button size="sm" onClick={() => setAsking(true)} disabled={readOnly || saving || !buffer} data-testid="full-editor-save">
            <Icon name="save" style={{ fontSize: 16 }} /> Save version
          </Button>
        )}
      </div>
      {draft && (
        <div className="flex flex-wrap items-center gap-3 border-b border-border bg-wine-soft px-3 py-2 text-sm text-wine" data-testid="full-editor-draft">
          <Icon name="history" style={{ fontSize: 16 }} />
          You have unsaved changes from {new Date(draft.updated_at).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })}.
          <Button size="sm" onClick={() => void restoreDraft()} data-testid="full-editor-restore">Restore them</Button>
          <Button size="sm" variant="outline" onClick={() => void discardDraft()} data-testid="full-editor-discard">Discard</Button>
        </div>
      )}
      {locked && (
        <div className="flex items-center gap-3 border-b border-border bg-warning-soft px-3 py-2 text-sm text-warning-ink" data-testid="full-editor-locked">
          <Icon name="lock" style={{ fontSize: 16 }} /> {locked.by} is editing this document. You can read it here.
          {locked.canTakeOver && <Button size="sm" variant="outline" onClick={() => void lock(true)}>Take over</Button>}
        </div>
      )}
      {!model?.editable && model && !error && (
        <div className="border-b border-border bg-secondary/60 px-3 py-2 text-sm text-muted-foreground">You can read this document; editing needs edit access.</div>
      )}
      <div className="relative min-h-0 flex-1 overflow-hidden">
        {error ? (
          <div className="p-6 text-sm text-destructive" role="alert">{error}</div>
        ) : !buffer ? (
          <div className="p-6 text-sm text-muted-foreground">Opening the Word file…</div>
        ) : (
          <IntlProvider locale="en" messages={folioMessages as Record<string, unknown> as never}>
          <DocxEditor
            key={editorKey}
            ref={ref}
            documentBuffer={buffer}
            author={me?.name ?? "Precentis user"}
            mode={readOnly ? "viewing" : mode}
            readOnly={readOnly}
            showToolbar={!readOnly}
            showReviewControls
            showHeaderFooterEditing={!readOnly}
            showPrintButton={false}
            initialZoom="fit-width"
            onError={(e) => setError(e.message)}
            className="h-full"
          />
          </IntlProvider>
        )}
      </div>
      <Dialog open={asking} onOpenChange={(o) => !saving && setAsking(o)}>
        <DialogContent className="max-w-md" data-testid="full-editor-save-dialog">
          <DialogHeader>
            <DialogTitle>Save as a new version</DialogTitle>
            <DialogDescription>
              {mode === "suggesting"
                ? "Your tracked changes are recorded against your name; the saved version is the clean document, and History shows what you changed."
                : "Direct edits are saved as they are; History still shows what changed."}
            </DialogDescription>
          </DialogHeader>
          <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={1000} placeholder="What did you change? (optional)"
            className="w-full rounded-md border border-border bg-background px-2 py-1.5 text-sm" data-testid="full-editor-note" />
          <div className="flex justify-end gap-2">
            <Button variant="outline" size="sm" onClick={() => setAsking(false)} disabled={saving}>Cancel</Button>
            <Button size="sm" onClick={() => void save()} disabled={saving} data-testid="full-editor-confirm">{saving ? "Saving…" : "Save version"}</Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
