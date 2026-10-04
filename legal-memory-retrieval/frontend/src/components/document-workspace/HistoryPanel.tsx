import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  compareDocxUrl,
  compareVersions,
  editErrorMessage,
  getBlame,
  listCommits,
  restoreVersion,
  type BlameParagraph,
  type Commit,
} from "@/api/editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { VersionDiff } from "@/components/document-workspace/VersionDiff";
import { useApp } from "@/context/AppContext";
import { formatDate, formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

const KIND: Record<string, string> = {
  editor: "Edit",
  upload: "Upload",
  import: "Original text",
  restore: "Restore",
  review: "Review",
  assistant: "Assistant",
};

const sizeChange = (delta: number | null) =>
  delta === null || delta === 0 ? null : `${delta > 0 ? "+" : "−"}${Math.abs(delta).toLocaleString()} chars`;

/**
 * The document's versions as a commit log: what each one says it did, who made it, how much it changed. A version's
 * changes are shown against the one before it; any version can be made current again (as a new version, so the log is
 * never rewritten).
 */
export function HistoryPanel({
  documentId,
  openVersionId,
  onOpen,
}: {
  documentId: string;
  openVersionId?: string;
  onOpen: (versionId: string) => void;
}) {
  const { identityKey } = useApp();
  const commits = useQuery({
    queryKey: [identityKey, "doc-commits", documentId],
    queryFn: () => listCommits(documentId),
    enabled: Boolean(identityKey),
  });
  const [changes, setChanges] = useState<Commit | null>(null);
  const [restoring, setRestoring] = useState<Commit | null>(null);
  const rows = commits.data ?? [];
  const head = rows.find((c) => c.is_current);

  if (commits.isPending) return <p className="text-xs text-muted-foreground">Loading history…</p>;
  if (commits.isError) return <p className="text-xs text-destructive">The history could not be loaded.</p>;
  if (!rows.length) {
    return <p className="text-xs text-muted-foreground">Single unversioned text — upload a file to start a version history.</p>;
  }

  return (
    <div data-testid="document-versions">
      <SectionLabel>History</SectionLabel>
      <ol className="mt-3 space-y-2" data-testid="commit-log">
        {rows.map((c) => (
          <li key={c.version_id} data-testid="commit" data-version={c.version_number}
            className={cn("rounded-md border px-3 py-2 text-sm", c.version_id === openVersionId ? "border-border bg-wine-soft" : "border-transparent hover:bg-secondary")}>
            <div className="flex items-center justify-between gap-2">
              <button type="button" className="font-medium hover:underline" onClick={() => onOpen(c.version_id)}>
                {c.version_label || `Version ${c.version_number}`}
              </button>
              <span className="flex items-center gap-1.5">
                <span className="rounded bg-secondary px-1.5 py-0.5 text-[10px] uppercase tracking-wide text-muted-foreground">
                  {KIND[c.kind] ?? c.kind}
                </span>
                {c.is_current && <span className="text-[10px] font-semibold uppercase tracking-wide text-wine" data-testid="commit-current">Current</span>}
              </span>
            </div>
            {c.message && <p className="mt-1 line-clamp-3 text-xs" data-testid="commit-message">{c.message}</p>}
            <div className="mt-1 text-xs text-muted-foreground">
              {[c.author_name, formatDate(c.created_at), sizeChange(c.chars_delta)].filter(Boolean).join(" · ")}
            </div>
            <div className="mt-1.5 flex gap-1.5">
              {c.parent_version_id && (
                <Button size="sm" variant="outline" className="h-6 px-2 text-[11px]" onClick={() => setChanges(c)} data-testid="commit-changes">
                  Changes
                </Button>
              )}
              {!c.is_current && head && (
                <Button size="sm" variant="ghost" className="h-6 px-2 text-[11px]" onClick={() => setRestoring(c)} data-testid="commit-restore">
                  Restore
                </Button>
              )}
            </div>
          </li>
        ))}
      </ol>

      {changes && <ChangesDialog documentId={documentId} commit={changes} onClose={() => setChanges(null)} />}
      {restoring && head && (
        <RestoreDialog documentId={documentId} target={restoring} head={head} onClose={() => setRestoring(null)}
          onDone={(versionId) => { setRestoring(null); onOpen(versionId); }} />
      )}
    </div>
  );
}

function ChangesDialog({ documentId, commit, onClose }: { documentId: string; commit: Commit; onClose: () => void }) {
  const { identityKey } = useApp();
  const [tab, setTab] = useState<"changes" | "blame">("changes");
  const parent = commit.parent_version_id as string;
  const diff = useQuery({
    queryKey: [identityKey, "doc-diff", documentId, parent, commit.version_id],
    queryFn: () => compareVersions(documentId, parent, commit.version_id),
    enabled: Boolean(identityKey),
  });
  const blame = useQuery({
    queryKey: [identityKey, "doc-blame", documentId, commit.version_id],
    queryFn: () => getBlame(documentId, commit.version_id),
    enabled: Boolean(identityKey) && tab === "blame",
  });
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-h-[85vh] max-w-3xl overflow-hidden" data-testid="changes-dialog">
        <DialogHeader>
          <DialogTitle>
            Version {commit.version_number} · {KIND[commit.kind] ?? commit.kind}
          </DialogTitle>
          <DialogDescription>
            {[commit.author_name, formatDateTime(commit.created_at)].filter(Boolean).join(" · ")}
            {diff.data ? ` · compared with version ${diff.data.from.version_number}` : ""}
          </DialogDescription>
        </DialogHeader>
        {commit.message && <p className="text-sm">{commit.message}</p>}
        <div className="flex items-center gap-1 border-b border-border text-xs" role="tablist">
          {([["changes", "Changes"], ["blame", "Who wrote what"]] as const).map(([k, label]) => (
            <button key={k} type="button" role="tab" aria-selected={tab === k} onClick={() => setTab(k)} data-testid={`changes-tab-${k}`}
              className={cn("rounded-t px-3 py-1.5", tab === k ? "border-b-2 border-wine font-medium" : "text-muted-foreground hover:bg-secondary")}>
              {label}
            </button>
          ))}
          <a className="ml-auto pb-1 text-muted-foreground hover:text-foreground hover:underline" data-testid="changes-redline"
            href={compareDocxUrl(documentId, parent, commit.version_id)}>
            <Icon name="download" style={{ fontSize: 14, verticalAlign: "-2px" }} /> Redline (.docx)
          </a>
        </div>
        <div className="min-h-0 overflow-y-auto pr-1" style={{ maxHeight: "55vh" }}>
          {tab === "changes" ? (
            diff.isPending ? <p className="text-sm text-muted-foreground">Comparing…</p>
              : diff.isError ? <p className="text-sm text-destructive">{editErrorMessage(diff.error)}</p>
              : <VersionDiff result={diff.data} />
          ) : blame.isPending ? <p className="text-sm text-muted-foreground">Working out who wrote what…</p>
            : blame.isError ? <p className="text-sm text-destructive">{editErrorMessage(blame.error)}</p>
            : <Blame paragraphs={blame.data.paragraphs} />}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Paragraphs with the version and person that last changed each; the label is shown where the owner changes. */
function Blame({ paragraphs }: { paragraphs: BlameParagraph[] }) {
  return (
    <div className="space-y-1" data-testid="blame">
      {paragraphs.map((p, i) => {
        const first = i === 0 || paragraphs[i - 1].version_id !== p.version_id;
        return (
          <div key={p.pid} className="grid grid-cols-[150px_minmax(0,1fr)] gap-3 text-sm" data-testid="blame-row" data-version={p.version_number}>
            <div className="pt-0.5 text-xs text-muted-foreground">
              {first && (
                <>
                  <span className="font-medium text-foreground">{p.before_window ? `before v${p.version_number}` : `v${p.version_number}`}</span>
                  <br />{p.author}<br />{p.at ? formatDate(p.at) : ""}
                </>
              )}
            </div>
            <p className={cn("border-l-2 pl-3 leading-relaxed", first ? "border-wine/50" : "border-border")}>{p.text}</p>
          </div>
        );
      })}
    </div>
  );
}

function RestoreDialog({ documentId, target, head, onClose, onDone }: {
  documentId: string;
  target: Commit;
  head: Commit;
  onClose: () => void;
  onDone: (versionId: string) => void;
}) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const restore = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await restoreVersion(documentId, { version_id: target.version_id, base_version_id: head.version_id, note: note.trim() || undefined });
      await queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(documentId) });
      toast(`Restored version ${out.restored_version_number} as version ${out.version_number}`);
      onDone(out.version_id);
    } catch (err) {
      setError(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(open) => !open && !busy && onClose()}>
      <DialogContent className="max-w-md" data-testid="restore-dialog">
        <DialogHeader>
          <DialogTitle>Restore version {target.version_number}?</DialogTitle>
          <DialogDescription>
            It becomes the current version as a new version {head.version_number + 1}. Version {head.version_number} and everything
            before it stay in the history.
          </DialogDescription>
        </DialogHeader>
        <textarea value={note} onChange={(e) => setNote(e.target.value)} rows={2} maxLength={1000} placeholder="Why? (optional)"
          className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
          data-testid="restore-note" />
        {error && <p className="text-sm text-destructive" data-testid="restore-error">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={busy}>Cancel</Button>
          <Button size="sm" onClick={() => void restore()} disabled={busy} data-testid="restore-confirm">
            {busy ? "Restoring…" : "Restore"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
