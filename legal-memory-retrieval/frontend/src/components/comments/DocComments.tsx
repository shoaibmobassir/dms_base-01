import { useEffect, useMemo, useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  addComment,
  deleteComment,
  editErrorMessage,
  listComments,
  setCommentStatus,
  type CommentThread,
} from "@/api/editor";
import { useConfirm } from "@/components/common/Confirm";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import type { MarksLocated, ViewerMark, ViewerSelection, ViewerTarget } from "@/components/viewer/DocumentViewer";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const when = (iso: string) => new Date(iso).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" });

/** Where the reader's selection is on screen, so the comment box can sit beside it. */
type Anchor = { x: number; y: number };

/**
 * Comments on a document, the way a notes app does them: select text, press Comment, write.
 * A thread's text is marked on the page only while that thread is the one you opened.
 * Shared by the document page and the editor's exact view, so a comment is the same everywhere.
 */
export function useDocComments({
  documentId,
  versionId,
  canAdd,
}: {
  documentId: string;
  /** The version being read; comments shown are the ones on it (plus carried ones). */
  versionId?: string;
  /** False when reading an earlier version or a rendering that lays out differently. */
  canAdd: boolean;
}) {
  const { identityKey, me, toast } = useApp();
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const key = [identityKey, "doc-comments", documentId, versionId ?? "current"];
  const comments = useQuery({ queryKey: key, queryFn: () => listComments(documentId, versionId), enabled: Boolean(identityKey) });
  const refresh = () => queryClient.invalidateQueries({ queryKey: [identityKey, "doc-comments", documentId] });

  const [located, setLocated] = useState<MarksLocated>({});
  const [selection, setSelectionState] = useState<ViewerSelection | null>(null);
  const [anchor, setAnchor] = useState<Anchor | null>(null);
  const [composing, setComposing] = useState(false);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [active, setActive] = useState<string | null>(null);
  const [showResolved, setShowResolved] = useState(false);
  const [target, setTarget] = useState<ViewerTarget | null>(null);

  const threads = comments.data?.threads ?? [];
  const visible = threads.filter((t) => showResolved || t.status === "open");
  const labels = useMemo(() => new Map(threads.map((t, i) => [t.comment_id, String(i + 1)])), [threads]);
  // Boxes are drawn for the opened thread only; the others are a numbered badge in the margin.
  const marks: ViewerMark[] = visible.map((t) => ({
    id: t.comment_id,
    page: t.page,
    // Threads from earlier versions, and comments from Word or the Assistant (no page boxes), are found again by their quote.
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

  /** From the viewer: the reader selected text (or cleared the selection). */
  const onSelectText = (s: ViewerSelection | null) => {
    if (!canAdd) return;
    if (s) {
      const sel = window.getSelection();
      const rect = sel && sel.rangeCount ? sel.getRangeAt(0).getBoundingClientRect() : null;
      if (rect && (rect.width || rect.height)) setAnchor({ x: rect.left + rect.width / 2, y: rect.top });
      setSelectionState(s);
    } else if (!composing) {
      // A comment being written stays when a click elsewhere clears the selection.
      setSelectionState(null);
      setAnchor(null);
    }
  };

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

  const cancel = () => {
    setDraft("");
    setComposing(false);
    setSelectionState(null);
    setAnchor(null);
    window.getSelection()?.removeAllRanges();
  };

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
      cancel();
      setActive(c.comment_id);
    }, "Comment added");

  const remove = async (commentId: string) => {
    if (await confirm({ title: "Delete this comment?", description: "Replies to it stay with the thread.", confirmLabel: "Delete comment" }))
      await run(() => deleteComment(documentId, commentId), "Comment deleted");
  };

  return {
    documentId, comments, threads, visible, labels, marks, detached, focusThread, located, setLocated,
    selection, anchor, composing, setComposing, draft, setDraft, busy, active, setActive, showResolved, setShowResolved,
    target, setTarget, onSelectText, run, submit, cancel, remove, canAdd, myId: me?.member_id ?? null,
  };
}

export type DocComments = ReturnType<typeof useDocComments>;

/** The small "Comment" button that appears over selected text, and the box it opens. */
export function SelectionComment({ dc }: { dc: DocComments }) {
  const input = useRef<HTMLTextAreaElement>(null);
  const { selection, anchor, composing, canAdd } = dc;
  useEffect(() => {
    if (composing) input.current?.focus();
  }, [composing]);
  // The button follows the page: it goes away when the page is scrolled.
  useEffect(() => {
    if (!selection || composing) return;
    const hide = () => dc.cancel();
    window.addEventListener("scroll", hide, true);
    return () => window.removeEventListener("scroll", hide, true);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selection, composing]);

  if (!canAdd || !selection || !anchor) return null;
  const left = Math.min(Math.max(anchor.x - (composing ? 150 : 48), 8), window.innerWidth - (composing ? 308 : 104));
  const top = Math.max(anchor.y - (composing ? 168 : 44), 8);

  if (!composing) {
    return (
      <button
        type="button"
        // Pressing the button must not clear the selection it is about.
        onMouseDown={(e) => e.preventDefault()}
        onClick={() => dc.setComposing(true)}
        style={{ position: "fixed", left, top, zIndex: 60 }}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-popover px-2.5 py-1.5 text-xs font-medium text-foreground shadow-lg hover:bg-secondary"
        data-testid="comment-pill"
      >
        <Icon name="add_comment" style={{ fontSize: 16 }} /> Comment
      </button>
    );
  }
  return (
    <div
      style={{ position: "fixed", left, top, zIndex: 60, width: 300 }}
      className="space-y-2 rounded-lg border border-border bg-popover p-3 shadow-xl"
      data-testid="comment-composer"
    >
      <p className="line-clamp-2 border-l-2 border-warning/60 pl-2 text-xs italic text-muted-foreground">“{selection.quote}”</p>
      <textarea
        ref={input}
        value={dc.draft}
        onChange={(e) => dc.setDraft(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && (e.metaKey || e.ctrlKey) && dc.draft.trim()) void dc.submit();
          if (e.key === "Escape") dc.cancel();
        }}
        placeholder="Add a comment…"
        rows={3}
        maxLength={5000}
        aria-label="Comment"
        className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="comment-input"
      />
      <div className="flex justify-end gap-2">
        <Button size="sm" variant="outline" onClick={dc.cancel}>
          Cancel
        </Button>
        <Button size="sm" disabled={!dc.draft.trim() || dc.busy} onClick={() => void dc.submit()} data-testid="comment-submit">
          Comment
        </Button>
      </div>
    </div>
  );
}

/** Every thread on the document, newest context first; opening one marks its text on the page. */
export function CommentsPanel({
  dc,
  onViewVersion,
  note,
}: {
  dc: DocComments;
  /** Open an earlier version where a carried comment was made. */
  onViewVersion: (versionId: string, number: number | null, commentId: string) => void;
  /** Why commenting is off here (reading an earlier version, a different rendering). */
  note?: string;
}) {
  const { comments, threads, visible } = dc;
  return (
    <div className="flex min-h-0 flex-1 flex-col" data-testid="editor-comments">
      <div className="px-4 pb-2 pt-3">
        {dc.canAdd ? (
          <p className="text-xs text-muted-foreground">
            <Icon name="add_comment" style={{ fontSize: 14, verticalAlign: "-2px" }} /> Select text on a page to comment on it.
          </p>
        ) : (
          <p className="text-xs text-muted-foreground">{note ?? "Commenting is off here."}</p>
        )}
      </div>
      <div className="flex items-center justify-between border-y border-border px-4 py-2">
        <span className="text-sm font-semibold">
          Comments <span className="font-normal text-muted-foreground">{threads.filter((t) => t.status === "open").length} open</span>
        </span>
        <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
          <input type="checkbox" checked={dc.showResolved} onChange={(e) => dc.setShowResolved(e.target.checked)} data-testid="comments-show-resolved" />
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
            label={dc.labels.get(t.comment_id) ?? ""}
            active={t.comment_id === dc.active}
            mine={t.author_id === dc.myId}
            detached={dc.detached(t)}
            onViewOrigin={() => {
              onViewVersion(t.version_id, t.version_number, t.comment_id);
              dc.setLocated({});
              dc.setActive(t.comment_id);
            }}
            myId={dc.myId}
            busy={dc.busy}
            onFocus={() => dc.focusThread(t)}
            onReply={(body) => dc.run(() => addComment(dc.documentId, { body, parent_id: t.comment_id }))}
            onStatus={(status) => dc.run(() => setCommentStatus(dc.documentId, t.comment_id, status), status === "resolved" ? "Resolved" : "Reopened")}
            onDelete={(cid) => void dc.remove(cid)}
          />
        ))}
      </ul>
    </div>
  );
}

function Thread({
  thread, label, active, mine, detached, onViewOrigin, myId, busy, onFocus, onReply, onStatus, onDelete,
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
              aria-label="Reply"
              rows={2}
              maxLength={5000}
              className="w-full resize-y rounded-md border border-border bg-background px-2 py-1 text-sm focus:outline-none focus-visible:ring-2 focus-visible:ring-ring"
              data-testid="comment-reply-input"
            />
          )}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="outline" disabled={busy} onClick={() => onStatus(resolved ? "open" : "resolved")} data-testid="comment-resolve">
              {resolved ? "Reopen" : "Resolve"}
            </Button>
            {!resolved && (
              <Button size="sm" disabled={!reply.trim() || busy} onClick={() => void onReply(reply).then(() => setReply(""))} data-testid="comment-reply-submit">
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
