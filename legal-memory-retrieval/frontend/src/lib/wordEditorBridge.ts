import { useSyncExternalStore } from "react";

// A Word editor open in the workbench registers itself by document, so the Assistant's edit cards can hand it
// suggestions (plan 22, W3.3). Plain module state: there is at most one editor per document per window.

export type SuggestEdit = { id: string; original: string; proposed: string; op?: string };
export type SuggestResult = { suggested: number; skipped: { id: string; reason: string }[]; error?: string };
type Suggest = (edits: SuggestEdit[]) => SuggestResult;

const editors = new Map<string, Suggest>();
const listeners = new Set<() => void>();
const notify = () => listeners.forEach((l) => l());

export function registerWordEditor(documentId: string, suggest: Suggest): () => void {
  editors.set(documentId, suggest);
  notify();
  return () => {
    if (editors.get(documentId) === suggest) editors.delete(documentId);
    notify();
  };
}

/** Whether a Word editor for this document is open (and can take suggestions) in this window. */
export function useWordEditorOpen(documentId: string): boolean {
  return useSyncExternalStore(
    (cb) => {
      listeners.add(cb);
      return () => listeners.delete(cb);
    },
    () => editors.has(documentId),
    () => false,
  );
}

export function suggestInWordEditor(documentId: string, edits: SuggestEdit[]): SuggestResult {
  const suggest = editors.get(documentId);
  if (!suggest) return { suggested: 0, skipped: edits.map((e) => ({ id: e.id, reason: "The Word editor is not open" })), error: "The Word editor is not open for this document" };
  return suggest(edits);
}
