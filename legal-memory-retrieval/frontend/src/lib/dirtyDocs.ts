import { useSyncExternalStore } from "react";

// Documents with edits that are not saved as a version yet (the Word editor reports them). The workbench reads this
// to mark tabs and to ask before closing one; nothing here is persisted.

const dirty = new Set<string>();
const listeners = new Set<() => void>();
let snapshot: ReadonlySet<string> = new Set();

function emit() {
  snapshot = new Set(dirty);
  for (const l of listeners) l();
}

export function setDocDirty(documentId: string, value: boolean) {
  if (value === dirty.has(documentId)) return;
  if (value) dirty.add(documentId);
  else dirty.delete(documentId);
  emit();
}

export function isDocDirty(documentId: string): boolean {
  return dirty.has(documentId);
}

export function useDirtyDocs(): ReadonlySet<string> {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => snapshot,
  );
}
