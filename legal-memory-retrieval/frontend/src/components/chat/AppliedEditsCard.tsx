import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { Eye, History, Loader2, PencilLine, Undo2 } from "lucide-react";
import { toast } from "sonner";
import { undoEdits } from "@/api/chat";
import { Segments } from "@/components/document-workspace/VersionDiff";
import { errorText } from "@/components/chat/MessageParts";
import { cn } from "@/lib/utils";

type Segment = { t: "eq" | "del" | "ins"; text: string };

export type AppliedChange = {
  op: "replace" | "insert_after" | "delete";
  before: string;
  after: string;
  page?: number | null;
  segments?: Segment[] | null;
};

/** One write of the Assistant's edits into a document (an ``edits_applied`` event). */
export type AppliedEvent = {
  type: "edits_applied";
  document_id: string;
  filename?: string;
  from_version_id: string;
  to_version_id: string;
  version_number: number;
  changes: AppliedChange[];
  failed?: { before: string; after: string; reason: string }[];
  undone_version_id?: string;
  undone_version_number?: number;
};

const SHOWN = 12;

/**
 * What the Assistant changed in a document, as it is now: old → new for each change, the new version, and Undo
 * (which restores the version from before this answer's changes, as a new version).
 */
export function AppliedEditsCard({
  groups,
  sessionId,
  messageId,
  onView,
}: {
  /** The answer's writes to one document, in order. */
  groups: AppliedEvent[];
  sessionId?: string;
  /** Undefined while the answer is still being written. */
  messageId?: string;
  onView: (change: AppliedChange) => void;
}) {
  const queryClient = useQueryClient();
  const last = groups[groups.length - 1];
  const documentId = last.document_id;
  const [undone, setUndone] = useState<number | null>(last.undone_version_number ?? null);
  const [busy, setBusy] = useState(false);
  const [all, setAll] = useState(false);
  const changes = groups.flatMap((g) => g.changes);
  const failed = groups.flatMap((g) => g.failed ?? []);

  // The document changed: whatever shows it (an open panel, the document page, History) reloads.
  useEffect(() => {
    void queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(documentId) });
  }, [queryClient, documentId, last.to_version_id, undone]);

  const undo = async () => {
    if (!sessionId || !messageId) return;
    setBusy(true);
    try {
      const out = await undoEdits(sessionId, messageId, documentId);
      setUndone(out.version_number);
      toast.success(`Undone: the document is back to version ${out.restored_version_number} (saved as version ${out.version_number}).`);
    } catch (err) {
      toast.error(errorText(err, "Could not undo these changes."));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className={cn("mb-3 rounded-lg border border-border", undone !== null && "opacity-75")} data-testid="applied-edits">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-secondary/40 px-3 py-2">
        <PencilLine className="h-3.5 w-3.5 shrink-0 text-wine" />
        <span className="min-w-0 flex-1 truncate text-xs font-semibold text-ink" data-testid="applied-edits-title">
          {undone !== null ? "Undone" : "Changed"} {last.filename ?? "the document"} · version {undone ?? last.version_number}
        </span>
        <span className="text-xs text-muted-foreground">{changes.length} change{changes.length === 1 ? "" : "s"}</span>
        <Link
          to={`/documents/${encodeURIComponent(documentId)}?panel=versions`}
          className="inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          <History className="h-3 w-3" /> History
        </Link>
        <button
          type="button"
          onClick={() => void undo()}
          disabled={busy || undone !== null || !messageId}
          title={!messageId ? "Available when the answer is finished" : undone !== null ? "Already undone" : "Go back to the version before these changes"}
          data-testid="applied-edits-undo"
          className="inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium hover:bg-secondary disabled:opacity-40"
        >
          {busy ? <Loader2 className="h-3 w-3 animate-spin" /> : <Undo2 className="h-3 w-3" />}
          {undone !== null ? "Undone" : "Undo"}
        </button>
      </div>
      <ul className="divide-y divide-border">
        {(all ? changes : changes.slice(0, SHOWN)).map((c, i) => (
          <li key={i} className="space-y-1 px-3 py-2" data-testid="applied-change" data-op={c.op}>
            <div className="flex items-center justify-between gap-2 text-xs text-muted-foreground">
              <span>
                {c.op === "insert_after" ? "Added" : c.op === "delete" ? "Removed" : "Changed"}
                {c.page ? ` · page ${c.page}` : ""}
              </span>
              {undone === null && (
                <button type="button" onClick={() => onView(c)} className="inline-flex items-center gap-1 hover:text-foreground">
                  <Eye className="h-3 w-3" /> Show in document
                </button>
              )}
            </div>
            <p className="text-[12.5px] leading-relaxed">
              {c.op === "replace" && c.segments?.length ? (
                <Segments segments={c.segments} />
              ) : c.op === "delete" ? (
                <del className="rounded-sm bg-red-500/10 px-0.5 text-red-900 decoration-red-500/70 dark:text-red-200">{c.before}</del>
              ) : (
                <ins className="rounded-sm bg-emerald-500/10 px-0.5 text-emerald-900 no-underline dark:text-emerald-200">{c.after}</ins>
              )}
            </p>
          </li>
        ))}
      </ul>
      {changes.length > SHOWN && !all && (
        <button type="button" onClick={() => setAll(true)} className="w-full border-t border-border py-2 text-xs text-muted-foreground hover:text-foreground">
          Show {changes.length - SHOWN} more
        </button>
      )}
      {failed.length > 0 && (
        <div className="border-t border-border bg-warning-soft px-3 py-2 text-xs text-warning-ink" data-testid="applied-edits-failed">
          {failed.length} edit{failed.length === 1 ? "" : "s"} could not be placed in the document:
          <ul className="mt-1 list-disc pl-4">
            {failed.slice(0, 5).map((f, i) => (
              <li key={i} className="truncate">{(f.after || f.before).slice(0, 120)} ({f.reason})</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
