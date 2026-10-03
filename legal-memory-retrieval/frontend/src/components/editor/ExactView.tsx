import { Suspense, lazy, useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addComment,
  deleteComment,
  editErrorMessage,
  listComments,
  setCommentStatus,
  type CommentThread,
} from "@/api/editor";
import { Button } from "@/components/ui/button";
import { useConfirm } from "@/components/common/Confirm";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";
import type { MarksLocated, ViewerMark, ViewerSelection, ViewerTarget } from "@/components/viewer/DocumentViewer";
import { ReviewPanel } from "@/components/editor/ReviewPanel";

const DocumentViewer = lazy(() => import("@/components/viewer/DocumentViewer").then((m) => ({ default: m.DocumentViewer })));

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/**
 * The document exactly as filed (rendered pages) with comments: select text on a page to
 * comment on it; threads are listed beside the pages and marked on them.
 */
/** What the sidebar shows: the comment threads, or Word's reviewing pane. */
export type ExactSide = { kind: "comments" } | {
  kind: "review";
  baseVersionId: string;
  canWrite: boolean;
  onNewVersion: (versionNumber: number, note: string) => void;
};

export function ExactView({ documentId, currentVersionId, side = { kind: "comments" }, showViews = false }: {
  documentId: string;
  currentVersionId: string;
  side?: ExactSide;
  /** Offer Markup / Final / Original (Word files with tracked changes). */
  showViews?: boolean;
}) {
  const [renderView, setRenderView] = useState<"markup" | "final" | "original">("markup");
  const { identityKey, me, toast } = useApp();
  const confirm = useConfirm();
  const queryClient = useQueryClient();
  // null = the current version; otherwise an earlier version opened from a detached thread.
  const [viewing, setViewing] = useState<{ versionId: string; number: number | null } | null>(null);
  const key = [identityKey, "doc-comments", documentId, viewing?.versionId ?? "current"];
  const comments = useQuery({
    queryKey: key,
    queryFn: () => listComments(documentId, viewing?.versionId),
    enabled: Boolean(identityKey),
  });
  const refresh = () => queryClient.invalidateQueries({ queryKey: [identityKey, "doc-comments", documentId] });
  const [located, setLocated] = useState<MarksLocated>({});

  const [selection, setSelection] = useState<ViewerSelection | null>(null);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  const threads = comments.data?.threads ?? [];
  const visible = threads.filter((t) => showResolved || t.status === "open");
  const labels = useMemo(() => new Map(threads.map((t, i) => [t.comment_id, String(i + 1)])), [threads]);
  // Threads from earlier versions are found again by their quote; their saved boxes belong to that version.
  const marks: ViewerMark[] = visible.map((t) => ({
    id: t.comment_id,
    page: t.page,
    // Threads from earlier versions, and comments that came from Word (no page boxes), are
    // found again by their quote.
    boxes: t.carried || !t.rects.length ? [] : t.rects,
    quote: t.carried || !t.rects.length ? t.quote : undefined,
    label: labels.get(t.comment_id) ?? "",
    active: t.comment_id === active,
    muted: t.status === "resolved",
  }));
  const detached = (t: CommentThread) => t.carried && (!t.quote || located[t.comment_id] === null);

  const focusThread = (t: CommentThread) => {
    setActive(t.comment_id);
    const page = t.carried ? located[t.comment_id] : t.page;
    if (page) setTarget({ page, quote: "", nonce: Date.now() });
  };
  // Comments are placed on the pages as filed; the Final / Original renditions lay out differently.
  const readOnlyVersion = Boolean(viewing) || renderView !== "markup";

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
      if (done) toast(done);
    } catch (err) {
      toast(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  const composing = Boolean(selection) || draft.trim().length > 0;
  const submit = () =>
    selection &&
    run(async () => {
      const c = await addComment(documentId, {
        body: draft,
        version_id: comments.data?.version_id,
        page: selection.page,
        rects: selection.boxes,
        quote: selection.quote,
      });
      setDraft("");
      setSelection(null);
      setActive(c.comment_id);
      window.getSelection()?.removeAllRanges();
    }, "Comment added");

  return (
    <div className="grid flex-1 gap-6 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      {viewing && (
        <div className="flex items-center gap-3 rounded-md border border-warning/60 bg-warning-soft px-3 py-2 text-sm xl:col-span-2" data-testid="exact-old-version">
          <Icon name="history" style={{ fontSize: 16 }} />
          Viewing v{viewing.number ?? "?"}, an earlier version, as it was when the comment was made.
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => { setViewing(null); setLocated({}); }}>
            Back to the current version
          </Button>
        </div>
      )}
      {/* contain: fit-width pages must not widen the layout that sizes them */}
      <div className="flex h-[calc(100dvh-14rem)] min-w-0 flex-col overflow-hidden rounded-md border border-border bg-card [contain:inline-size]" data-testid="editor-exact">
        {showViews && (
          <div className="flex items-center gap-1 border-b border-border px-2 py-1 text-xs" role="tablist" aria-label="Show">
            {([["markup", "All markup"], ["final", "Final"], ["original", "Original"]] as const).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={renderView === k} onClick={() => setRenderView(k)} data-testid={`exact-view-${k}`}
                className={cn("rounded px-2 py-0.5", renderView === k ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary")}>
                {label}
              </button>
            ))}
            <span className="ml-2 text-muted-foreground">
              {renderView === "markup" ? "As filed, with tracked changes" : renderView === "final" ? "Every change accepted" : "Every change rejected"}
            </span>
          </div>
        )}
        <div className="min-h-0 flex-1">
        <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading pages…</p>}>
          <DocumentViewer
            key={`${viewing?.versionId ?? currentVersionId}-${renderView}`}
            src={`/api/documents/${encodeURIComponent(documentId)}/render?version_id=${encodeURIComponent(viewing?.versionId ?? currentVersionId)}${renderView !== "markup" ? `&view=${renderView}` : ""}`}
            target={target}
            marks={marks}
            onMarkClick={(cid) => {
              setActive(cid);
              document.getElementById(`comment-${cid}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
            }}
            onMarksLocated={setLocated}
            onSelectText={(s) => {
              // Keep a started comment when the selection is cleared by a click elsewhere.
              if (s || !draft.trim()) setSelection(s);
            }}
          />
        </Suspense>
        </div>
      </div>

      {side.kind === "review" ? (
        <aside className="flex max-h-[calc(100dvh-14rem)] min-h-0 flex-col">
          <ReviewPanel documentId={documentId} baseVersionId={side.baseVersionId} canWrite={side.canWrite}
            onNewVersion={side.onNewVersion} onJump={(quote) => setTarget({ page: null, quote, nonce: Date.now() })} />
        </aside>
      ) : (
      <aside className="flex max-h-[calc(100dvh-14rem)] min-h-0 flex-col gap-3" data-testid="editor-comments">
        <div className="rounded-lg border border-border bg-card p-4">
          {readOnlyVersion ? (
            <p className="text-xs text-muted-foreground">{viewing ? "Comments are added on the current version." : "Switch to All markup to add comments."}</p>
          ) : composing && selection ? (
            <div className="space-y-2" data-testid="comment-composer">
              <p className="line-clamp-3 border-l-2 border-warning/60 pl-2 text-xs italic text-muted-foreground">“{selection.quote}”</p>
              <textarea
                autoFocus
                value={draft}
                onChange={(e) => setDraft(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && draft.trim()) void submit();
                }}
                placeholder="Add a comment…"
                rows={3}
                maxLength={5000}
                className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
                data-testid="comment-input"
              />
              <div className="flex justify-end gap-2">
                <Button size="sm" variant="outline" onClick={() => { setDraft(""); setSelection(null); }}>Cancel</Button>
                <Button size="sm" disabled={!draft.trim() || busy} onClick={() => void submit()} data-testid="comment-submit">Comment</Button>
              </div>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">
              <Icon name="add_comment" style={{ fontSize: 14, verticalAlign: "-2px" }} /> Select text on a page to comment on it.
            </p>
          )}
        </div>

        <div className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card">
          <div className="flex items-center justify-between border-b border-border px-4 py-2">
            <span className="text-sm font-semibold">
              Comments <span className="font-normal text-muted-foreground">{threads.filter((t) => t.status === "open").length} open</span>
            </span>
            <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
              <input type="checkbox" checked={showResolved} onChange={(e) => setShowResolved(e.target.checked)} data-testid="comments-show-resolved" />
              Show resolved
            </label>
          </div>
          {comments.data && comments.data.on_other_versions > 0 && (
            <p className="border-b border-border px-4 py-2 text-xs text-muted-foreground">
              {comments.data.on_other_versions} comment thread{comments.data.on_other_versions === 1 ? "" : "s"} on earlier versions.
            </p>
          )}
          <ul className="min-h-0 flex-1 space-y-2 overflow-y-auto p-3" data-testid="comment-list">
            {comments.isLoading && <li className="text-xs text-muted-foreground">Loading comments…</li>}
            {comments.isError && <li className="text-xs text-destructive">{editErrorMessage(comments.error)}</li>}
            {comments.data && visible.length === 0 && <li className="text-xs text-muted-foreground">No comments yet.</li>}
            {visible.map((t) => (
              <Thread
                key={t.comment_id}
                thread={t}
                label={labels.get(t.comment_id) ?? ""}
                active={t.comment_id === active}
                mine={t.author_id === me?.member_id}
                detached={detached(t)}
                onViewOrigin={() => {
                  setViewing({ versionId: t.version_id, number: t.version_number });
                  setLocated({});
                  setActive(t.comment_id);
                }}
                myId={me?.member_id ?? null}
                busy={busy}
                onFocus={() => focusThread(t)}
                onReply={(body) => run(() => addComment(documentId, { body, parent_id: t.comment_id }))}
                onStatus={(status) => run(() => setCommentStatus(documentId, t.comment_id, status), status === "resolved" ? "Resolved" : "Reopened")}
                onDelete={async (cid) => {
                  if (await confirm({ title: "Delete this comment?", description: "Replies to it stay with the thread.", confirmLabel: "Delete comment" }))
                    await run(() => deleteComment(documentId, cid), "Comment deleted");
                }}
              />
            ))}
          </ul>
        </div>
      </aside>
      )}
    </div>
  );
}

function Thread({
  thread,
  label,
  active,
  mine,
  detached,
  onViewOrigin,
  myId,
  busy,
  onFocus,
  onReply,
  onStatus,
  onDelete,
}: {
  thread: CommentThread;
  label: string;
  active: boolean;
  mine: boolean;
  detached: boolean;
  onViewOrigin: () => void;
  myId: string | null;
  busy: boolean;
  onFocus: () => void;
  onReply: (body: string) => Promise<unknown>;
  onStatus: (status: "open" | "resolved") => void;
  onDelete: (commentId: string) => void;
}) {
  const [reply, setReply] = useState("");
  const resolved = thread.status === "resolved";
  return (
    <li
      id={`comment-${thread.comment_id}`}
      className={cn("rounded-md border p-3 text-sm transition-colors", active ? "border-warning/60 bg-warning-soft" : "border-border", resolved && "opacity-70")}
      data-testid="comment-thread"
      data-status={thread.status}
    >
      <button type="button" className="block w-full text-left" onClick={onFocus}>
        <div className="mb-1 flex items-center gap-2 text-xs text-muted-foreground">
          <span className="inline-flex h-5 min-w-5 items-center justify-center rounded-full bg-warning px-1 font-semibold text-black">{label}</span>
          <span>p. {thread.page}</span>
          {resolved && <span className="rounded bg-secondary px-1.5">Resolved{thread.resolved_by ? ` by ${thread.resolved_by}` : ""}</span>}
          {thread.carried && <span className="rounded bg-secondary px-1.5" data-testid="comment-carried">from v{thread.version_number ?? "?"}</span>}
          {thread.source === "word" && <span className="rounded bg-info-soft px-1.5 text-info" data-testid="comment-from-word">Word</span>}
        </div>
        {thread.quote && (
          <p className={cn("mb-1.5 line-clamp-2 border-l-2 pl-2 text-xs italic text-muted-foreground", detached ? "border-muted-foreground/40 line-through" : "border-warning/60")}>
            “{thread.quote}”
          </p>
        )}
      </button>
      {detached && (
        <p className="mb-1.5 text-xs text-muted-foreground" data-testid="comment-detached">
          The text has changed since v{thread.version_number ?? "?"}.{" "}
          <button type="button" className="text-primary underline" onClick={onViewOrigin} data-testid="comment-view-origin">
            View it on v{thread.version_number ?? "?"}
          </button>
        </p>
      )}
      <Message author={thread.author} at={thread.created_at} body={thread.body} canDelete={mine} onDelete={() => onDelete(thread.comment_id)} />
      {thread.replies.map((r) => (
        <div key={r.comment_id} className="mt-2 border-l border-border pl-3">
          <Message author={r.author} at={r.created_at} body={r.body} canDelete={r.author_id === myId} onDelete={() => onDelete(r.comment_id)} />
        </div>
      ))}
      {active && (
        <div className="mt-2 space-y-2">
          {!resolved && (
            <textarea
              value={reply}
              onChange={(e) => setReply(e.target.value)}
              placeholder="Reply…"
              rows={2}
              maxLength={5000}
              className="w-full resize-y rounded-md border border-border bg-background px-2 py-1 text-sm outline-none focus:ring-2 focus:ring-ring"
              data-testid="comment-reply-input"
            />
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onStatus(resolved ? "open" : "resolved")} data-testid="comment-resolve">
              {resolved ? "Reopen" : "Resolve"}
            </Button>
            {!resolved && (
              <Button
                size="sm"
                disabled={!reply.trim() || busy}
                onClick={() => void onReply(reply).then(() => setReply(""))}
                data-testid="comment-reply-submit"
              >
                Reply
              </Button>
            )}
          </div>
        </div>
      )}
    </li>
  );
}

function Message({ author, at, body, canDelete, onDelete }: { author: string | null; at: string; body: string; canDelete: boolean; onDelete: () => void }) {
  return (
    <div>
      <div className="flex items-baseline justify-between gap-2">
        <span className="text-xs font-semibold">{author ?? "Unknown"}</span>
        <span className="flex items-center gap-1 text-xs text-muted-foreground">
          {when(at)}
          {canDelete && (
            <button type="button" title="Delete" aria-label="Delete comment" className="rounded p-0.5 hover:bg-secondary" onClick={onDelete}>
              <Icon name="delete" style={{ fontSize: 14 }} />
            </button>
          )}
        </span>
      </div>
      <p className="whitespace-pre-wrap break-words text-sm">{body}</p>
    </div>
  );
}
