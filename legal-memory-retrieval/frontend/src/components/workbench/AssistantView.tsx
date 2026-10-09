import { useCallback, useEffect, useLayoutEffect, useRef, useState, type DragEvent } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import { formatDate } from "@/lib/format";
import { createSession, getSession, listWorkspaceSessions, streamMessage } from "@/api/chat";
import { usePlaybooks } from "@/api/playbooks";
import type { Attachment, Citation } from "@/api/types";
import type { WorkspaceKind } from "@/api/workspaces";
import { AssistantMessage } from "@/components/chat/AssistantMessage";
import type { PanelSource } from "@/components/chat/CitationDocumentPanel";
import type { UiMessage } from "@/components/chat/chatTypes";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { attachmentKey, attachmentLabel, hasPageDrag, pageAttachment, readPageDrag } from "@/lib/pageDrag";
import { cn } from "@/lib/utils";
import type { OpenRequest } from "./Explorer";

export type OpenDoc = { documentId: string; title: string };

/**
 * The Assistant in the workbench (plan 22, W3): one conversation per workspace that knows its documents. The documents
 * open in tabs go with every question (they can be left out one by one), pages dragged from a document go as page
 * references, and sources open as tabs beside the work.
 */
export function AssistantView({
  kind,
  id,
  label,
  openDocs,
  onOpen,
  seed,
}: {
  kind: Exclude<WorkspaceKind, "firm">;
  id: string;
  label: string;
  openDocs: OpenDoc[];
  onOpen: (r: OpenRequest) => void;
  /** Text to put in the composer (e.g. "Follow the playbook …"); changes of ``nonce`` re-apply it. */
  seed?: { text: string; nonce: number; send?: boolean };
}) {
  const queryClient = useQueryClient();
  const { identityKey } = useApp();
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [text, setText] = useState("");
  const [left, setLeft] = useState<Set<string>>(new Set());
  const [pages, setPages] = useState<Attachment[]>([]);
  const [streaming, setStreaming] = useState(false);
  const [dropping, setDropping] = useState(false);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const slash = text.startsWith("/") ? text.slice(1).toLowerCase() : null;
  const playbooks = usePlaybooks({ kind: "instructions", enabled: slash !== null });
  const matches = slash === null ? [] : (playbooks.data ?? []).filter((p) => p.title.toLowerCase().includes(slash)).slice(0, 8);
  const [loaded, setLoaded] = useState(false);
  const sentSeed = useRef<number | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const history = useQuery({
    queryKey: [identityKey, "workspace-sessions", kind, id],
    queryFn: () => listWorkspaceSessions(kind, id),
    enabled: showHistory && identityKey !== null,
  });
  const openSession = async (sid: string) => {
    abortRef.current?.abort();
    const d = await getSession(sid);
    setSessionId(sid);
    setMessages(d.messages);
    setShowHistory(false);
  };

  // The latest conversation of this workspace, if there is one.
  useEffect(() => {
    let cancelled = false;
    setMessages([]);
    setSessionId(null);
    setLoaded(false);
    listWorkspaceSessions(kind, id)
      .then(async (sessions) => {
        if (cancelled || !sessions.length) return;
        const d = await getSession(sessions[0].id);
        if (cancelled) return;
        setSessionId(sessions[0].id);
        setMessages(d.messages);
      })
      .catch(() => undefined)
      .finally(() => {
        if (!cancelled) setLoaded(true);
      });
    return () => {
      cancelled = true;
      abortRef.current?.abort();
    };
  }, [kind, id, identityKey]);

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const attached: Attachment[] = [
    ...openDocs.filter((d) => !left.has(d.documentId)).map((d) => ({ document_id: d.documentId, filename: d.title || d.documentId })),
    ...pages,
  ];

  const patchLast = useCallback((fn: (m: UiMessage) => UiMessage) => {
    setMessages((prev) => (prev.length ? [...prev.slice(0, -1), fn(prev[prev.length - 1])] : prev));
  }, []);

  const send = async (content: string, files: Attachment[] = attached) => {
    const prompt = content.trim();
    if (!prompt || streaming) return;
    let sid = sessionId;
    if (!sid) {
      const s = await createSession(undefined, undefined, { kind, id });
      sid = s.id;
      setSessionId(sid);
    }
    const now = new Date().toISOString();
    setMessages((prev) => [
      ...prev,
      { id: `u-${now}`, session_id: sid!, role: "user", content: prompt, files, created_at: now } as UiMessage,
      { id: `a-${now}`, session_id: sid!, role: "assistant", content: "", events: [], citations: [], created_at: now, status: "streaming", prompt, promptFiles: files } as UiMessage,
    ]);
    setText("");
    setPages([]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      await streamMessage(
        sid,
        prompt,
        {
          onDelta: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
          onFinalText: (t) => patchLast((m) => ({ ...m, content: t, citations: [] })),
          onEvent: (ev) => patchLast((m) => ({ ...m, events: [...(m.events ?? []), ev] })),
          onCitation: (c) => patchLast((m) => ({ ...m, citations: [...(m.citations ?? []), c] })),
          onTitle: () => undefined,
          onError: (message) => patchLast((m) => ({ ...m, status: "error", error: message })),
          onStart: (messageId) => patchLast((m) => ({ ...m, id: messageId })),
        },
        controller.signal,
        { files },
      );
      patchLast((m) => (m.status === "streaming" ? { ...m, status: undefined } : m));
    } catch (err) {
      patchLast((m) => ({ ...m, status: controller.signal.aborted ? "stopped" : "error", error: err instanceof Error ? err.message : "The request failed" }));
    } finally {
      abortRef.current = null;
      setStreaming(false);
      // Accepted edits change documents open in tabs: show the new version.
      void queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("document") || q.queryKey.includes("doc-commits") });
    }
  };

  // A seed fills the composer; one marked ``send`` is asked straight away, once the conversation has loaded.
  useEffect(() => {
    if (!seed?.text || sentSeed.current === seed.nonce) return;
    if (!seed.send) {
      sentSeed.current = seed.nonce;
      setText(seed.text);
    } else if (loaded && !streaming) {
      sentSeed.current = seed.nonce;
      void send(seed.text);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps -- send reads the latest state
  }, [seed?.nonce, seed?.text, seed?.send, loaded, streaming]);

  const openSource = (s: Omit<PanelSource, "nonce"> | null) => {
    if (!s) return;
    const q = s.quotes?.[0];
    const p = new URLSearchParams();
    if (q?.page) p.set("page", String(q.page));
    onOpen({ documentId: s.documentId, title: s.title ?? "", toSide: true, params: p.toString() });
  };
  const openCitation = (c?: Citation) => {
    if (!c?.document_id) return;
    const page = (c.quotes?.[0] as { page?: number } | undefined)?.page;
    const p = new URLSearchParams();
    if (page) p.set("page", String(page));
    if (c.chunk_id) p.set("chunk", String(c.chunk_id));
    onOpen({ documentId: String(c.document_id), title: String(c.title ?? ""), toSide: true, params: p.toString() });
  };

  const onDrop = (e: DragEvent) => {
    setDropping(false);
    const page = readPageDrag(e);
    if (!page) return;
    e.preventDefault();
    const att = pageAttachment(page);
    setPages((prev) => (prev.some((a) => attachmentKey(a) === attachmentKey(att)) ? prev : [...prev, att]));
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-assistant">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Assistant · {label}</div>
        <button type="button" title="Earlier conversations in this workspace" aria-label="Earlier conversations" aria-expanded={showHistory}
          className={cn("rounded p-1 hover:bg-secondary hover:text-foreground", showHistory ? "text-wine" : "text-muted-foreground")}
          onClick={() => setShowHistory((v) => !v)} data-testid="assistant-history">
          <Icon name="history" style={{ fontSize: 17 }} />
        </button>
        {sessionId && (
          <Link to={`/chat/${encodeURIComponent(sessionId)}`} title="Open in the Assistant page" aria-label="Open in the Assistant page"
            className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" data-testid="assistant-open-full">
            <Icon name="open_in_full" style={{ fontSize: 16 }} />
          </Link>
        )}
        <button type="button" title="New conversation" aria-label="New conversation"
          className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={() => { abortRef.current?.abort(); setSessionId(null); setMessages([]); }} data-testid="assistant-new">
          <Icon name="add_comment" style={{ fontSize: 17 }} />
        </button>
      </div>
      {showHistory && (
        <div className="max-h-56 shrink-0 overflow-y-auto border-b border-border bg-paper" data-testid="assistant-history-list">
          {history.isPending ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">Loading…</p>
          ) : !(history.data ?? []).length ? (
            <p className="px-3 py-2 text-xs text-muted-foreground">No earlier conversations in this workspace.</p>
          ) : (
            <ul className="divide-y divide-border">
              {(history.data ?? []).map((h) => (
                <li key={h.id}>
                  <button type="button" onClick={() => void openSession(h.id)}
                    className={cn("w-full px-3 py-1.5 text-left text-xs hover:bg-secondary", h.id === sessionId && "bg-wine-soft text-wine")}>
                    <span className="block truncate font-medium">{h.title || "Untitled conversation"}</span>
                    <span className="text-muted-foreground">{formatDate(h.updated_at)}</span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      )}
      <div ref={scrollRef} className="min-h-0 flex-1 space-y-4 overflow-y-auto px-3 py-3 text-sm">
        {messages.length === 0 ? (
          <div className="space-y-2 text-xs text-muted-foreground">
            <p>Ask about the documents of this workspace. The ones open in tabs go with your question; drag a page here to point at it.</p>
            {(openDocs.length === 0
              ? ["What is in this workspace, and what is each document about?", "List the key dates and deadlines across this workspace's documents.",
                "Which documents here mention a hearing, an order or a deadline?"]
              : openDocs.length === 1
                ? [`Summarise “${openDocs[0].title || "the open document"}” in a page.`, "What deadlines or dates does it set?",
                  "Compare the open document with the firm's precedents on the same points and note where it departs."]
                : ["Summarise the open documents and what each one argues.", "What deadlines or dates appear in these documents?",
                  "Compare the relief sought in the open documents."]).map((s) => (
              <button key={s} type="button" className="block w-full rounded-md border border-border px-2.5 py-1.5 text-left text-[12px] text-foreground hover:bg-secondary"
                onClick={() => void send(s)} data-testid="assistant-starter">{s}</button>
            ))}
          </div>
        ) : (
          messages.map((m, i) =>
            m.role === "user" ? (
              <div key={m.id} className="ml-6 rounded-lg bg-secondary px-3 py-2 text-[13px]" data-testid="assistant-user-message">
                {m.content}
                {m.files?.length ? <div className="mt-1 truncate text-[11px] text-muted-foreground">{m.files.map(attachmentLabel).join(" · ")}</div> : null}
              </div>
            ) : (
              <div key={m.id} className="text-[13px]" data-testid="assistant-answer">
                <AssistantMessage
                  message={m}
                  sessionId={sessionId ?? undefined}
                  isLast={i === messages.length - 1}
                  onRetry={m.prompt ? () => { setMessages((prev) => prev.slice(0, -2)); void send(m.prompt!, m.promptFiles ?? []); } : undefined}
                  onOpenCitation={openCitation}
                  onOpenSource={openSource}
                  onAnswer={(t, files) => void send(t, files)}
                  onUpload={async () => null}
                />
              </div>
            ),
          )
        )}
      </div>
      <div
        className={cn("border-t border-border p-2", dropping && "bg-wine-soft")}
        onDragOver={(e) => { if (hasPageDrag(e)) { e.preventDefault(); setDropping(true); } }}
        onDragLeave={() => setDropping(false)}
        onDrop={onDrop}
        data-testid="assistant-composer"
      >
        {(openDocs.length > 0 || pages.length > 0) && (
          <div className="mb-1.5 flex flex-wrap gap-1">
            {openDocs.map((d) => {
              const off = left.has(d.documentId);
              return (
                <button key={d.documentId} type="button" aria-pressed={!off}
                  title={off ? "Not sent — click to include" : "Sent with your question — click to leave out"}
                  onClick={() => setLeft((prev) => { const n = new Set(prev); if (n.has(d.documentId)) n.delete(d.documentId); else n.add(d.documentId); return n; })}
                  className={cn("flex max-w-[180px] items-center gap-1 rounded-full border px-2 py-0.5 text-[11px]",
                    off ? "border-dashed border-border text-muted-foreground line-through" : "border-wine/40 bg-wine-soft text-wine")}
                  data-testid="assistant-context-doc">
                  <Icon name="description" style={{ fontSize: 12 }} /> <span className="truncate">{d.title || d.documentId}</span>
                </button>
              );
            })}
            {pages.map((a) => (
              <span key={attachmentKey(a)} className="flex max-w-[200px] items-center gap-1 rounded-full border border-wine/40 bg-wine-soft px-2 py-0.5 text-[11px] text-wine">
                <Icon name="article" style={{ fontSize: 12 }} /> <span className="truncate">{attachmentLabel(a)}</span>
                <button type="button" aria-label="Remove" onClick={() => setPages((prev) => prev.filter((x) => attachmentKey(x) !== attachmentKey(a)))}>
                  <Icon name="close" style={{ fontSize: 11 }} />
                </button>
              </span>
            ))}
          </div>
        )}
        {slash !== null && (
          <ul className="mb-1.5 max-h-48 overflow-y-auto rounded-md border border-border bg-card text-[12px]" role="listbox" aria-label="Playbooks" data-testid="assistant-slash">
            {matches.length === 0 && <li className="px-2.5 py-1.5 text-muted-foreground">{playbooks.isPending ? "Loading playbooks…" : "No playbook matches"}</li>}
            {matches.map((p) => (
              <li key={p.playbook_id}>
                <button type="button" className="w-full px-2.5 py-1.5 text-left hover:bg-secondary" role="option" aria-selected={false}
                  onClick={() => setText(`Follow the playbook “${p.title}” (${p.playbook_id}). `)}>
                  <span className="font-medium">{p.title}</span>
                  {p.summary && <span className="block truncate text-muted-foreground">{p.summary}</span>}
                </button>
              </li>
            ))}
          </ul>
        )}
        <form className="flex items-end gap-1.5" onSubmit={(e) => { e.preventDefault(); void send(text); }}>
          <textarea
            value={text}
            onChange={(e) => {
              setText(e.target.value);
              // Grow with the text up to the max height, so a long instruction stays readable.
              e.target.style.height = "auto";
              e.target.style.height = `${Math.min(e.target.scrollHeight, 240)}px`;
            }}
            onKeyDown={(e) => {
              // Enter while an IME is composing (Hindi, Chinese, Japanese …) confirms the word; it must not send.
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && e.keyCode !== 229) {
                e.preventDefault();
                void send(text);
              }
            }}
            rows={3}
            placeholder={dropping ? "Drop the page here" : "Ask about these documents, or type / for a playbook"}
            aria-label="Ask the Assistant"
            className="max-h-60 min-h-[4.5rem] flex-1 resize-none rounded-md border border-border bg-card px-2.5 py-1.5 text-[13px] focus-visible:border-wine/60 focus-visible:outline-none"
            data-testid="assistant-input"
          />
          {streaming ? (
            <Button type="button" size="sm" variant="outline" onClick={() => abortRef.current?.abort()}>Stop</Button>
          ) : (
            <Button type="submit" size="sm" disabled={!text.trim()} aria-label="Send" data-testid="assistant-send">
              <Icon name="arrow_upward" style={{ fontSize: 16 }} />
            </Button>
          )}
        </form>
      </div>
    </div>
  );
}
