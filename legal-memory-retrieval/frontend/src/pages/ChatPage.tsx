import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useLocation, useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  createSession,
  deleteSession,
  getSession,
  listModels,
  listSessions,
  listSuggestions,
  renameSession,
  streamMessage,
  updateSession,
  type WorkMode,
} from "@/api/chat";
import { apiFetch, authHeaders } from "@/api/client";
import type { AskInputItem, Attachment, ChatEvent, ChatMessage, ChatSession, Citation, DocumentItem, EditProposal, Paged, Matter } from "@/api/types";
import { CitationDocumentPanel, displayQuote, sourceFromCitation, type PanelSource } from "@/components/chat/CitationDocumentPanel";
import { HistoryPane } from "@/components/chat/HistoryPane";
import { ReviewTableCard, type ReviewTableEvent } from "@/components/chat/ReviewTableCard";
import { MatterScopePicker, type MatterChoice } from "@/components/chat/MatterScopePicker";
import { useDocuments, useMatter } from "@/api/resources";
import { AskInputsCard, EditProposalsCard, FileCard, StepTimeline, errorText, type EditGroup } from "@/components/chat/MessageParts";
import { Markdown } from "@/components/chat/Markdown";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";
import { attachmentKey, attachmentLabel, hasPageDrag, pageAttachment, readPageDrag } from "@/lib/pageDrag";
import {
  Sparkles,
  Paperclip,
  Scale,
  FileText,
  Search,
  Copy,
  Check,
  RotateCcw,
  Link2,
  ShieldCheck,
  ArrowUpRight,
  GitCompare,
  FileEdit,
  FileSearch,
  FileSpreadsheet,
  X,
  Plus,
  History,
} from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

// ── helpers ─────────────────────────────────────────────────────────────────

type UiMessage = ChatMessage & {
  status?: "streaming" | "stopped" | "error";
  error?: string;
  prompt?: string;
  promptFiles?: Attachment[];
};

function useMediaQuery(query: string) {
  const [matches, setMatches] = useState(() => window.matchMedia(query).matches);
  useEffect(() => {
    const mq = window.matchMedia(query);
    const onChange = () => setMatches(mq.matches);
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, [query]);
  return matches;
}

// ── page ────────────────────────────────────────────────────────────────────

export function ChatPage() {
  const { sessionId } = useParams();
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { identityKey, toast: appToast } = useApp();

  const sessionsKey = [identityKey, "chat-sessions"];
  const sessions = useQuery({ queryKey: sessionsKey, queryFn: listSessions, enabled: !!identityKey });
  const models = useQuery({ queryKey: ["chat-models"], queryFn: listModels, staleTime: Infinity });
  const suggestions = useQuery({ queryKey: [identityKey, "chat-suggestions"], queryFn: listSuggestions, enabled: !!identityKey });

  const [messages, setMessages] = useState<UiMessage[]>([]);
  const [loadedSession, setLoadedSession] = useState<ChatSession | null>(null);
  // Matter chosen before the first message creates the conversation.
  const [pendingMatter, setPendingMatter] = useState<MatterChoice | null>(null);
  const [loadingThread, setLoadingThread] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState<string | undefined>(undefined);
  const abortRef = useRef<AbortController | null>(null);
  const scrollRef = useRef<HTMLDivElement>(null);
  const skipLoadRef = useRef<string | null>(null);

  const refreshSessions = useCallback(() => queryClient.invalidateQueries({ queryKey: sessionsKey }), [queryClient, sessionsKey]);

  useEffect(() => {
    const def = models.data?.models.find((m) => m.default) ?? models.data?.models[0];
    if (def && !model) setModel(def.id);
  }, [models.data, model]);

  // Load the thread when the selected session changes.
  useEffect(() => {
    if (!sessionId) {
      setMessages([]);
      return;
    }
    if (skipLoadRef.current === sessionId) {
      skipLoadRef.current = null;
      return;
    }
    let cancelled = false;
    setLoadingThread(true);
    getSession(sessionId)
      .then((d) => {
        if (cancelled) return;
        setLoadedSession(d.session);
        setMessages(
          d.messages.map((m) => ({
            ...m,
            status: m.events?.some((e) => e.type === "stopped") ? "stopped" : undefined,
          })),
        );
      })
      .catch(() => {
        if (!cancelled) {
          appToast("That conversation is not available.");
          navigate("/chat", { replace: true });
        }
      })
      .finally(() => !cancelled && setLoadingThread(false));
    return () => {
      cancelled = true;
    };
  }, [sessionId, navigate, appToast]);

  // Stop any in-flight answer when leaving the page or switching persona.
  useEffect(() => () => abortRef.current?.abort(), [identityKey]);

  useLayoutEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
  }, [messages]);

  const [attachments, setAttachments] = useState<Attachment[]>([]);

  const patchLast = (fn: (m: UiMessage) => UiMessage) =>
    setMessages((prev) => {
      const next = [...prev];
      const last = next[next.length - 1];
      if (last?.role === "assistant") next[next.length - 1] = fn(last);
      return next;
    });

  const send = async (text: string, files: Attachment[] = attachments) => {
    const content = text.trim();
    if (!content || streaming) return;
    const sentFiles = files;
    if (files === attachments) setAttachments([]);

    let id = sessionId;
    if (!id) {
      try {
        const created = await createSession(model, pendingMatter?.matter_id);
        setPendingMatter(null);
        id = created.id;
        skipLoadRef.current = id;
        navigate(`/chat/${id}`, { replace: true });
      } catch (err) {
        appToast(err instanceof Error ? err.message : "Could not start a conversation");
        return;
      }
    }

    setMessages((prev) => [
      ...prev,
      { role: "user", content, files: sentFiles },
      { role: "assistant", content: "", events: [], citations: [], status: "streaming", prompt: content, promptFiles: sentFiles },
    ]);
    setStreaming(true);
    const controller = new AbortController();
    abortRef.current = controller;

    try {
      await streamMessage(
        id,
        content,
        {
          onDelta: (t) => patchLast((m) => ({ ...m, content: m.content + t })),
          // The server re-sends the answer after checking every statement against its source.
          onFinalText: (t) => patchLast((m) => ({ ...m, content: t, citations: [] })),
          onEvent: (ev) => patchLast((m) => ({ ...m, events: [...(m.events ?? []), ev] })),
          onCitation: (c) => patchLast((m) => ({ ...m, citations: [...(m.citations ?? []), c] })),
          onTitle: () => void refreshSessions(),
          onError: (message) => patchLast((m) => ({ ...m, status: "error", error: message })),
          onStart: (messageId) => patchLast((m) => ({ ...m, id: messageId })),
        },
        controller.signal,
        { mode: workMode, files: sentFiles },
      );
      patchLast((m) => (m.status === "streaming" ? { ...m, status: undefined } : m));
    } catch (err) {
      if (controller.signal.aborted) {
        patchLast((m) => ({ ...m, status: "stopped" }));
      } else {
        patchLast((m) => ({ ...m, status: "error", error: err instanceof Error ? err.message : "The request failed" }));
      }
    } finally {
      abortRef.current = null;
      setStreaming(false);
      void refreshSessions();
    }
  };

  const retry = (prompt: string, files: Attachment[] = []) => {
    setMessages((prev) => prev.slice(0, -2));
    void send(prompt, files);
  };

  const sessionList = sessions.data ?? [];
  // The history list can lag behind a conversation opened elsewhere (e.g. from a matter page).
  const active = sessionList.find((s) => s.id === sessionId) ?? (loadedSession?.id === sessionId ? loadedSession : undefined);
  const modelOptions = models.data?.models ?? [];

  // Every document cited in this thread, with the citations that point at it.
  const threadDocs: { documentId: string; title: string; citations: Citation[] }[] = [];
  for (const m of messages) {
    if (m.role !== "assistant") continue;
    for (const c of (m.citations ?? []) as Citation[]) {
      const documentId = String(c.document_id ?? "");
      if (!documentId) continue;
      const doc = threadDocs.find((d) => d.documentId === documentId);
      if (doc) doc.citations.push(c);
      else threadDocs.push({ documentId, title: String(c.title ?? documentId), citations: [c] });
    }
  }

  const isWide = useMediaQuery("(min-width: 1280px)");
  const roomForBoth = useMediaQuery("(min-width: 1680px)");
  const [rightTab, setRightTab] = useState<"document" | "sources" | null>(null);
  // Wide screens dock the history pane and remember it; smaller ones use a sheet that always starts closed.
  const [dockOpen, setDockOpen] = useState(() => {
    try {
      return window.localStorage.getItem("chat.historyOpen") === "1";
    } catch {
      return false;
    }
  });
  const [sheetOpen, setSheetOpen] = useState(false);
  // History and the evidence panel share the width: below 1680px the open panel wins, without changing the saved choice.
  const historyOpen = isWide ? dockOpen && (!rightTab || roomForBoth) : sheetOpen;
  const setHistoryOpen = (open: boolean) => {
    if (!isWide) {
      setSheetOpen(open);
      return;
    }
    if (open && rightTab && !roomForBoth) setRightTab(null);
    setDockOpen(open);
    try {
      window.localStorage.setItem("chat.historyOpen", open ? "1" : "0");
    } catch {
      // storage unavailable
    }
  };

  // "All conversations" links here with ?history=open; matter pages with ?matter=<id>
  // (a new conversation limited to that matter, created when the first message is sent).
  const [searchParams, setSearchParams] = useSearchParams();
  const matterParam = searchParams.get("matter");
  const linkedMatter = useMatter(matterParam ?? "");
  useEffect(() => {
    if (searchParams.get("history") !== "open") return;
    setHistoryOpen(true);
    setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [searchParams]);
  useEffect(() => {
    const m = linkedMatter.data?.matter;
    if (!matterParam || !m) return;
    setPendingMatter({ matter_id: m.matter_id, matter_code: m.matter_code, title: m.title });
    setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [matterParam, linkedMatter.data]);
  const [workMode, setWorkMode] = useState<WorkMode>("cite");
  const [source, setSource] = useState<PanelSource | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [draft, setDraft] = useState<{ text: string; nonce: number }>();
  const nonceRef = useRef(0);
  // The document viewer hands over the pages the lawyer dragged to the Assistant (and what they typed): they become
  // attachments and the box is pre-filled; nothing is sent until the lawyer sends it.
  const location = useLocation();
  useEffect(() => {
    const hand = (location.state as { handoff?: { pages?: Attachment[]; prompt?: string } } | null)?.handoff;
    if (!hand) return;
    (hand.pages ?? []).forEach((p) => attach(p));
    if (hand.prompt) setDraft({ text: hand.prompt, nonce: Date.now() });
    navigate(location.pathname + location.search, { replace: true, state: null });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [location.state]);
  // Ask the Firm hands a question over with ?q= (and usually ?matter=): pre-fill it, never auto-send.
  const handedQuestion = searchParams.get("q");
  useEffect(() => {
    if (!handedQuestion) return;
    setDraft({ text: handedQuestion, nonce: Date.now() });
    if (!matterParam) setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handedQuestion]);

  const openSource = (next: Omit<PanelSource, "nonce"> | null) => {
    if (!next) return;
    setSource({ ...next, nonce: ++nonceRef.current });
    setRightTab("document");
  };

  const openCitation = (c?: Citation) => {
    if (!c) return;
    openSource(sourceFromCitation(c, 0));
  };

  const splitRef = useRef<HTMLDivElement>(null);
  const clampPanel = useCallback((w: number) => {
    const total = splitRef.current?.clientWidth ?? window.innerWidth;
    return Math.round(Math.min(Math.max(w, 360), Math.max(360, total - 380)));
  }, []);
  const [panelWidth, setPanelWidth] = useState(() => {
    try {
      const saved = Number(window.localStorage.getItem("chat.panelWidth"));
      if (saved > 0) return saved;
    } catch {
      // storage unavailable
    }
    return Math.round(window.innerWidth * 0.45);
  });
  useEffect(() => {
    try {
      window.localStorage.setItem("chat.panelWidth", String(panelWidth));
    } catch {
      // storage unavailable
    }
  }, [panelWidth]);

  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const right = splitRef.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (ev: PointerEvent) => setPanelWidth(clampPanel(right - ev.clientX));
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  };

  const attach = (att: Attachment) =>
    setAttachments((list) => (list.some((a) => attachmentKey(a) === attachmentKey(att)) ? list : [...list, att]));

  /** File an uploaded document in the first open matter, index it, and return it as an attachment. */
  const uploadDocument = async (file: File): Promise<Attachment | null> => {
    setUploading(true);
    try {
      const matters = await apiFetch<Paged<Matter>>("/api/matters?limit=1");
      const matterId = matters.items[0]?.matter_id;
      if (!matterId) {
        toast.error("No matter is available to file this document.");
        return null;
      }
      const body = new FormData();
      body.append("matter_id", matterId);
      body.append("files", file);
      const created = await fetch("/api/uploads/batches", { method: "POST", headers: authHeaders(), body });
      if (!created.ok) throw new Error(await created.text());
      const batch = (await created.json()) as { batch_id: string };
      const ran = await fetch(`/api/uploads/batches/${encodeURIComponent(batch.batch_id)}/run`, {
        method: "POST",
        headers: authHeaders(),
      });
      if (!ran.ok && ran.status !== 202) throw new Error(await ran.text());

      type BatchFile = { status: string; document_id: string | null; error?: string | null };
      let files: BatchFile[] = ran.status === 202 ? [] : (((await ran.json()) as { batch?: { files?: BatchFile[] } }).batch?.files ?? []);
      // Queue mode: poll until the worker has indexed the file.
      for (let i = 0; i < 90 && !files.some((f) => f.document_id && f.status !== "pending"); i++) {
        await new Promise((r) => setTimeout(r, 2000));
        const polled = await apiFetch<{ batch: { files: BatchFile[] } }>(`/api/uploads/batches/${encodeURIComponent(batch.batch_id)}`);
        files = polled.batch.files;
      }
      const done = files.find((f) => f.document_id);
      if (!done?.document_id) throw new Error(files[0]?.error || "The document could not be indexed.");
      toast.success(`${file.name} is filed and attached.`);
      return { filename: file.name, document_id: done.document_id, content_type: file.type || undefined };
    } catch (err) {
      toast.error(errorText(err, "Upload failed"));
      return null;
    } finally {
      setUploading(false);
    }
  };

  const newConversation = () => {
    if (!isWide) setHistoryOpen(false);
    setPendingMatter(null);
    navigate("/chat");
  };

  const changeScope = async (choice: MatterChoice | null) => {
    if (!sessionId) {
      setPendingMatter(choice);
      return;
    }
    try {
      await updateSession(sessionId, { matter_id: choice?.matter_id ?? "" });
      void refreshSessions();
      appToast(choice ? `Searching only ${choice.title || choice.matter_code}` : "Searching every matter you can access");
    } catch (err) {
      appToast(err instanceof Error ? err.message : "Could not change the matter");
    }
  };

  // Alt+H (Option+H) shows or hides the history, from anywhere on the page.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!e.altKey || e.metaKey || e.ctrlKey || e.code !== "KeyH") return;
      e.preventDefault();
      setHistoryOpen(!historyOpen);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });
  const historyPane = (onCollapse?: () => void) => (
    <HistoryPane
      sessions={sessionList}
      activeId={sessionId}
      loading={sessions.isPending}
      onNew={newConversation}
      onOpen={(id) => {
        if (!isWide) setHistoryOpen(false);
        navigate(`/chat/${id}`);
      }}
      onRename={async (id, title) => {
        await renameSession(id, title);
        void refreshSessions();
      }}
      onPin={async (id, pinned) => {
        await updateSession(id, { pinned });
        void refreshSessions();
      }}
      onDelete={async (id) => {
        await deleteSession(id);
        void refreshSessions();
        if (id === sessionId) navigate("/chat");
      }}
      onCollapse={onCollapse}
    />
  );

  return (
    <div className="flex h-full min-h-0 bg-background">
      {/* History: docked beside the thread on wide screens, a sheet on small ones. */}
      {isWide && historyOpen && (
        <aside className="w-[272px] shrink-0 border-r border-border" aria-label="Conversation history">
          {historyPane(() => setHistoryOpen(false))}
        </aside>
      )}
      {!isWide && (
        <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
          <SheetContent side="left" className="w-full max-w-full p-0 sm:max-w-[360px]" aria-describedby={undefined}>
            <SheetTitle className="sr-only">Conversation history</SheetTitle>
            {historyPane()}
          </SheetContent>
        </Sheet>
      )}

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
      <header className="flex items-center justify-between gap-3 border-b border-border/80 bg-card/50 px-3 py-2 backdrop-blur-xs lg:px-4">
        <div className="flex min-w-0 items-center gap-1.5">
          {!(isWide && historyOpen) && (
            <button
              type="button"
              onClick={() => setHistoryOpen(true)}
              data-testid="chat-history-toggle"
              title="Show conversation history (Alt+H)"
              className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md border border-border bg-card px-2.5 text-xs font-medium text-foreground hover:bg-secondary"
            >
              <History className="h-4 w-4 text-muted-foreground" />
              <span className="hidden sm:inline">History</span>
            </button>
          )}
          <button
            type="button"
            onClick={newConversation}
            data-testid="chat-new"
            title="New conversation"
            aria-label="New conversation"
            className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-md px-2 text-xs font-medium text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <Plus className="h-4 w-4" />
            <span className="hidden md:inline">New</span>
          </button>
          <h1 className="ml-1 truncate font-display text-base font-semibold text-ink" data-testid="chat-title">
            {active?.title?.trim() || (sessionId ? "Untitled conversation" : "New conversation")}
          </h1>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {modelOptions.length > 1 && !sessionId && (
            <select
              value={model}
              onChange={(e) => setModel(e.target.value)}
              aria-label="Model"
              className="cursor-pointer rounded-md border border-border bg-card px-2 py-1 text-xs font-medium text-foreground focus:outline-hidden"
            >
              {modelOptions.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </select>
          )}
          <MatterScopePicker
            matterId={active?.matter_id}
            pending={sessionId ? null : pendingMatter}
            onChange={(choice) => void changeScope(choice)}
            disabled={streaming}
          />
          <button
            type="button"
            onClick={() => setRightTab(rightTab === "sources" ? null : "sources")}
            aria-pressed={rightTab === "sources"}
            data-testid="chat-sources-toggle"
            title={`${threadDocs.length} ${threadDocs.length === 1 ? "document" : "documents"} cited in this conversation`}
            className={cn(
              "flex items-center gap-1.5 rounded-md border px-2 py-1 text-xs font-medium transition-colors",
              rightTab === "sources" ? "border-wine/40 bg-wine-soft text-wine" : "border-border bg-card hover:bg-secondary",
            )}
          >
            <FileText className="h-3.5 w-3.5 text-amber-500" />
            <span>Sources</span>
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-amber-800 dark:text-amber-300">
              {threadDocs.length}
            </span>
          </button>
        </div>
      </header>

      <div ref={splitRef} className="relative flex min-h-0 flex-1 overflow-hidden">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">

        {/* Chat Thread Messages Area */}
        <div ref={scrollRef} className="flex-1 overflow-y-auto px-4 py-5 lg:px-6" data-testid="chat-thread">
          <div className="mx-auto max-w-3xl space-y-5">
            {loadingThread && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-10 justify-center">
                <Sparkles className="w-4 h-4 animate-spin text-primary" />
                <span>Loading conversation…</span>
              </div>
            )}

            {!loadingThread && messages.length === 0 && (
              <EmptyThread
                suggestions={suggestions.data ?? []}
                matterId={active?.matter_id ?? pendingMatter?.matter_id}
                onPick={(s) => void send(s)}
                onInsert={(text, file) => {
                  if (file) attach(file);
                  setDraft({ text, nonce: Date.now() });
                }}
              />
            )}

            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={m.id ?? i} className="flex flex-col items-end gap-1">
                  {(m.files ?? []).length > 0 && (
                    <div className="flex max-w-[85%] flex-wrap justify-end gap-1" data-testid="message-attachments">
                      {(m.files ?? []).map((f) => (
                        <button
                          key={`${f.document_id ?? f.filename}:${f.reference ? `${f.reference.unit}${f.reference.number}` : ""}`}
                          type="button"
                          onClick={() =>
                            f.document_id &&
                            openSource({ documentId: f.document_id, title: f.filename, label: "Attached document", quotes: [] })
                          }
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-foreground hover:bg-secondary"
                        >
                          <FileText className="h-3 w-3 text-amber-500" />
                          <span className="max-w-[220px] truncate">{attachmentLabel(f)}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  <div className="max-w-[85%] whitespace-pre-wrap rounded-2xl rounded-tr-xs bg-primary text-primary-foreground px-4 py-2.5 text-[14.5px] leading-relaxed shadow-2xs">
                    {m.content}
                  </div>
                </div>
              ) : (
                <AssistantMessage
                  key={m.id ?? i}
                  message={m}
                  sessionId={sessionId}
                  isLast={i === messages.length - 1}
                  onOpenCitation={openCitation}
                  onOpenSource={openSource}
                  onAnswer={(text, files) => void send(text, files)}
                  onUpload={uploadDocument}
                  onRetry={m.prompt ? () => retry(m.prompt!, m.promptFiles ?? []) : undefined}
                />
              ),
            )}
          </div>
        </div>

        {/* Large Professional Composer */}
        <Composer
          streaming={streaming}
          disabled={models.data ? !models.data.configured : false}
          mode={workMode}
          onMode={setWorkMode}
          uploading={uploading}
          attachments={attachments}
          draft={draft}
          onRemoveAttachment={(key) => setAttachments((list) => list.filter((a) => attachmentKey(a) !== key))}
          onDropPage={(page) => attach(pageAttachment(page))}
          onOpenAttachment={(a) => openSource({ documentId: a.document_id, title: a.filename, label: "Attached document", quotes: [] })}
          onUpload={(file) => void uploadDocument(file).then((att) => att && attach(att))}
          onPickDocuments={() => setPickerOpen(true)}
          onSend={(t) => void send(t)}
          onStop={() => abortRef.current?.abort()}
        />

      </section>

      {rightTab && (
        <>
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize document panel"
            tabIndex={0}
            onPointerDown={startResize}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") setPanelWidth((w) => clampPanel(w + 32));
              if (e.key === "ArrowRight") setPanelWidth((w) => clampPanel(w - 32));
            }}
            data-testid="split-handle"
            className="group relative hidden w-1.5 shrink-0 cursor-col-resize bg-border/70 transition-colors hover:bg-wine/40 focus-visible:bg-wine/50 focus-visible:outline-hidden lg:block"
          >
            <span className="absolute left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded bg-muted-foreground/40 group-hover:bg-wine" />
          </div>
          <div
            className="absolute inset-0 z-40 flex min-h-0 flex-col bg-card lg:static lg:z-auto lg:w-[var(--panel-w)] lg:shrink-0"
            style={{ ["--panel-w" as string]: `${panelWidth}px` }}
            data-testid="chat-right-panel"
          >
            <div className="flex items-center gap-1 border-b border-border px-2 py-1.5" role="tablist" aria-label="Evidence">
              {([
                ["document", "Document"],
                ["sources", `All sources · ${threadDocs.length}`],
              ] as const).map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="tab"
                  aria-selected={rightTab === id}
                  disabled={id === "document" && !source}
                  onClick={() => setRightTab(id)}
                  data-testid={`chat-panel-tab-${id}`}
                  className={cn(
                    "rounded-md px-2.5 py-1 text-xs disabled:opacity-40",
                    rightTab === id ? "bg-secondary font-semibold text-ink" : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {label}
                </button>
              ))}
              <button
                type="button"
                onClick={() => setRightTab(null)}
                aria-label="Close panel"
                title="Close panel"
                data-testid="chat-panel-close"
                className="ml-auto rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <X className="h-4 w-4" />
              </button>
            </div>
            <div className="min-h-0 flex-1">
              {rightTab === "document" && source ? (
                <CitationDocumentPanel source={source} />
              ) : (
                <ThreadSources docs={threadDocs} onOpen={(c) => openCitation(c)} />
              )}
            </div>
          </div>
        </>
      )}
      </div>
      </div>

      <DocumentPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        selected={attachments.map((a) => a.document_id)}
        onPick={(doc) => attach({ document_id: doc.document_id, filename: doc.title })}
      />
    </div>
  );
}

// ── every document cited in the conversation ──────────────────────────────────

type ThreadDoc = { documentId: string; title: string; citations: Citation[] };

function ThreadSources({ docs, onOpen }: { docs: ThreadDoc[]; onOpen: (c: Citation) => void }) {
  if (docs.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground" data-testid="thread-sources">
        No sources yet. Cited documents from this conversation appear here.
      </p>
    );
  }
  return (
    <div className="h-full space-y-3 overflow-y-auto p-3" data-testid="thread-sources">
      {docs.map((d) => (
        <div key={d.documentId} className="rounded-lg border border-border">
          <button
            type="button"
            onClick={() => onOpen(d.citations[0])}
            className="flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left hover:bg-secondary/50"
          >
            <FileText className="h-4 w-4 shrink-0 text-amber-500" />
            <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink">{d.title}</span>
            <span className="shrink-0 font-mono text-[11px] text-muted-foreground">
              {d.citations.length} {d.citations.length === 1 ? "citation" : "citations"}
            </span>
          </button>
          <div className="divide-y divide-border">
            {d.citations.map((c, i) => (
              <button
                key={i}
                type="button"
                onClick={() => onOpen(c)}
                className="block w-full px-3 py-2 text-left hover:bg-secondary/50"
              >
                <span className="line-clamp-2 text-[12px] italic text-muted-foreground">
                  {citationQuotes(c)[0] ? displayQuote(citationQuotes(c)[0]) : "Open the cited passage"}
                </span>
                {c.page != null && <span className="mt-0.5 block font-mono text-[11px] text-muted-foreground">p. {String(c.page)}</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}

// ── empty state ─────────────────────────────────────────────────────────────

/** Open-matter suggestions are whole questions and send at once; task cards drop a starting prompt into the box. */
/** Starter cards for a conversation limited to one matter: its own documents and next steps. */
function matterCards(matter: { title: string }, docs: DocumentItem[]) {
  const shortTitle = (t: string) => t.replace(/\.(docx?|pdf|txt)$/i, "");
  return [
    {
      title: "Where the matter stands",
      query: `Summarise where ${matter.title} stands: the parties, the issues, and what is due next.`,
      icon: <Scale className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />,
    },
    {
      title: "Draft a status note",
      query: `Draft a short status note to the client on ${matter.title}, citing the documents.`,
      icon: <FileEdit className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />,
    },
    ...docs.slice(0, 4).map((d) => ({
      title: `Review ${shortTitle(d.title)}`,
      query: `Review ${shortTitle(d.title)} and list the key risks and obligations.`,
      icon: <FileSearch className="w-4 h-4 text-amber-600 dark:text-amber-400" />,
      file: { document_id: d.document_id, filename: d.title } as Attachment,
    })),
  ];
}

function EmptyThread({
  suggestions,
  matterId,
  onPick,
  onInsert,
}: {
  suggestions: string[];
  matterId?: string | null;
  onPick: (s: string) => void;
  onInsert: (text: string, file?: Attachment) => void;
}) {
  const matter = useMatter(matterId ?? "");
  const matterDocs = useDocuments({ matter_id: matterId ?? undefined, limit: 4, enabled: !!matterId });
  const scoped = matterId && matter.data ? matterCards(matter.data.matter, matterDocs.data?.items ?? []) : null;
  const generic: { title: string; query: string; icon: React.ReactNode; file?: Attachment }[] = [
    {
      title: "Analyze a document",
      query: "Review this agreement and identify key risks.",
      icon: <FileSearch className="w-4 h-4 text-amber-600 dark:text-amber-400" />,
    },
    {
      title: "Find a clause",
      query: "Find all termination clauses across this matter.",
      icon: <Search className="w-4 h-4 text-blue-600 dark:text-blue-400" />,
    },
    {
      title: "Compare documents",
      query: "Compare the latest SPA against the previous version.",
      icon: <GitCompare className="w-4 h-4 text-purple-600 dark:text-purple-400" />,
    },
    {
      title: "Legal research",
      query: "What Indian cases discuss specific performance in similar circumstances?",
      icon: <Scale className="w-4 h-4 text-emerald-600 dark:text-emerald-400" />,
    },
    {
      title: "Draft",
      query: "Draft a concise NDA based on the attached precedent.",
      icon: <FileEdit className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />,
    },
    {
      title: "Summarize",
      query: "Summarize the key commercial terms of these contracts.",
      icon: <FileSpreadsheet className="w-4 h-4 text-rose-600 dark:text-rose-400" />,
    },
  ];

  return (
    <div className="select-none py-6 animate-in fade-in-50 duration-300">
      <div className="mx-auto mb-6 max-w-lg text-center">
        <h2 className="font-display text-2xl font-bold tracking-tight text-ink">
          What would you like to work on?
        </h2>
        <p className="mt-1.5 text-sm text-muted-foreground">
          Ask questions, analyze documents, research authorities, or draft.
        </p>
      </div>

      {!scoped && suggestions.length > 0 && (
        <div className="mb-6">
          <div className="meta-label mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground">
            From your open matters
          </div>
          <div className="space-y-0.5">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPick(s)}
                data-testid="chat-suggestion"
                className="group flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-[13px] transition-colors hover:bg-secondary"
              >
                <Icon name="chevron_right" className="text-muted-foreground group-hover:text-wine" style={{ fontSize: 14 }} />
                <span className="text-ink group-hover:text-wine">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}
      <div className="meta-label mb-1.5 text-[11px] uppercase tracking-wider text-muted-foreground" data-testid="chat-starters-label">
        {scoped && matter.data ? `Start on ${matter.data.matter.matter_code}` : "Start from a task"}
      </div>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
        {(scoped ?? generic).map((card, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onInsert(card.query, "file" in card ? card.file : undefined)}
            title="Put this prompt in the message box"
            data-testid="chat-starter"
            className="group flex cursor-pointer flex-col justify-between rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-wine/30 hover:bg-secondary/50"
          >
            <div className="mb-1.5 flex items-center gap-2">
              <span className="rounded-md bg-secondary p-1">{card.icon}</span>
              <h3 className="text-[13px] font-semibold text-ink group-hover:text-primary">{card.title}</h3>
            </div>
            <p className="line-clamp-2 text-[12px] leading-snug text-muted-foreground">&ldquo;{card.query}&rdquo;</p>
          </button>
        ))}
      </div>

    </div>
  );
}

// ── assistant message ───────────────────────────────────────────────────────

function AssistantMessage({
  message: m,
  sessionId,
  isLast,
  onRetry,
  onOpenCitation,
  onOpenSource,
  onAnswer,
  onUpload,
}: {
  message: UiMessage;
  sessionId?: string;
  isLast: boolean;
  onRetry?: () => void;
  onOpenCitation: (c?: Citation) => void;
  onOpenSource: (source: Omit<PanelSource, "nonce">) => void;
  onAnswer: (text: string, files: Attachment[]) => void;
  onUpload: (file: File) => Promise<Attachment | null>;
}) {
  const [copied, setCopied] = useState(false);
  const [madeFiles, setMadeFiles] = useState<{ document_id: string; filename: string }[]>([]);
  const citations = (m.citations ?? []) as Citation[];
  const events = (m.events ?? []) as ChatEvent[];
  const byRef = (n: number) => citations.find((c) => Number(c.ref) === n);
  const askItems = events.filter((e) => e.type === "ask_inputs").flatMap((e) => (e.items ?? []) as AskInputItem[]);
  const editGroups = events.filter((e) => e.type === "edit_proposals") as unknown as EditGroup[];
  const reviewTables = events.filter((e) => e.type === "review_table") as unknown as ReviewTableEvent[];
  const files = [
    ...events
      .filter((e) => e.type === "doc_created" && typeof e.document_id === "string")
      .map((e) => ({ document_id: String(e.document_id), filename: String(e.filename ?? "Document") })),
    ...madeFiles,
  ];
  const showEdit = (group: EditGroup, edit: EditProposal) =>
    onOpenSource({
      documentId: group.document_id,
      title: group.filename,
      label: "Suggested edit",
      quotes: [{ page: edit.page, quote: edit.original }],
    });

  const openCitation = (c?: Citation) => onOpenCitation(c);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(true);
      toast.success("Answer copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("Link to this conversation copied");
    } catch {
      // clipboard blocked
    }
  };
  const citedDocs = new Set(citations.map((c) => String(c.document_id ?? "")).filter(Boolean)).size;

  return (
    <div className="w-full" data-testid="assistant-message">
      <div className="min-w-0 rounded-xl border border-border bg-card p-5 shadow-2xs">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="font-mono text-[11px] text-muted-foreground" data-testid="message-citation-count">
            {citations.length > 0 &&
              `${citations.length} ${citations.length === 1 ? "citation" : "citations"} · ${citedDocs} ${citedDocs === 1 ? "document" : "documents"}`}
          </span>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => void copy()}
              title="Copy answer"
              aria-label="Copy answer"
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-emerald-600" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                title="Regenerate answer"
                aria-label="Regenerate answer"
                className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={() => void copyLink()}
              title="Copy link to this conversation"
              aria-label="Copy link to this conversation"
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Link2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <StepTimeline events={events} streaming={m.status === "streaming"} />

        {/* Formatted Legal Reasoning Content */}
        {m.content ? (
          <div className="text-[14.5px] leading-relaxed text-ink">
            <Markdown
              text={m.content}
              renderCitation={(n) => {
                const c = byRef(n);
                return (
                  <CitationBadge
                    num={n}
                    citation={c}
                    onOpen={() => openCitation(c)}
                  />
                );
              }}
            />
          </div>
        ) : m.status === "streaming" ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
            <span className="h-2 w-2 animate-pulse rounded-full bg-wine" />
            Reviewing relevant matter documents and statutory precedents…
          </p>
        ) : null}

        {askItems.length > 0 && (
          <AskInputsCard items={askItems} answered={!isLast || m.status === "streaming"} onSubmit={onAnswer} onUpload={onUpload} />
        )}

        {reviewTables.map((table, ti) => (
          <ReviewTableCard key={`${m.id ?? "live"}-review-${ti}`} table={table} onOpen={onOpenSource} />
        ))}

        {editGroups.map((group, gi) => (
          <EditProposalsCard
            key={`${m.id ?? "live"}-${gi}`}
            group={group}
            sessionId={sessionId}
            messageId={m.status === "streaming" ? undefined : m.id}
            onView={(edit) => showEdit(group, edit)}
            onFileReady={(f) => setMadeFiles((list) => [...list, f])}
          />
        ))}

        {files.map((f) => (
          <FileCard
            key={f.document_id}
            documentId={f.document_id}
            filename={f.filename}
            onOpen={() => onOpenSource({ documentId: f.document_id, title: f.filename, label: "Generated file", quotes: [], generated: true })}
          />
        ))}

        {m.status === "stopped" && (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="chat-stopped">
            Stopped — the partial answer above has been saved.
          </p>
        )}

        {/* Error handling */}
        {m.status === "error" && (
          <div className="mt-3 flex items-center justify-between gap-4 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs" data-testid="chat-error">
            <span className="text-destructive">{m.error ?? "The assistant could not complete the legal query."}</span>
            {onRetry && (
              <button type="button" onClick={onRetry} className="shrink-0 font-semibold text-foreground hover:underline cursor-pointer">
                Retry
              </button>
            )}
          </div>
        )}

        {/* Sources Grid */}
        {citations.length > 0 && (
          <div className="mt-4 pt-3 border-t border-border" data-testid="chat-sources">
            <div className="text-[10px] font-mono uppercase tracking-wider font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <FileText className="w-3 h-3 text-amber-500" />
              <span>Sources ({citations.length})</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {citations.map((c, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => openCitation(c)}
                  className="flex flex-col text-left p-2.5 rounded-lg border border-border hover:bg-secondary/50 transition-colors text-xs group cursor-pointer"
                >
                  <div className="flex items-center justify-between font-medium text-ink group-hover:text-primary">
                    <span className="truncate">
                      <span className="mr-1 font-mono-id text-wine font-semibold">[{String(c.ref ?? i + 1)}]</span>
                      {String(c.title ?? c.document_id ?? "Document")}
                    </span>
                    <ArrowUpRight className="w-3 h-3 text-muted-foreground group-hover:text-primary shrink-0" />
                  </div>
                  {citationQuotes(c).map((q, qi) => (
                    <p key={qi} className="mt-1 line-clamp-3 text-[11px] italic text-muted-foreground">
                      {quoted(q)}
                    </p>
                  ))}
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                    {c.page != null && <span className="font-mono">p. {String(c.page)}</span>}
                    {Array.isArray(c.quotes) && c.quotes.length > 1 && <span>{c.quotes.length} quotes</span>}
                    {c.support === "partial" && (
                      <span className="font-semibold text-amber-700 dark:text-amber-400" data-testid="citation-partial">
                        Partly supported
                      </span>
                    )}
                    {c.verified === false && (
                      <span className="font-semibold text-amber-700 dark:text-amber-400" data-testid="citation-unverified">
                        Not confirmed
                      </span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}

      </div>
    </div>
  );
}

/** A quote in curly quotation marks, unless the text already opens with one. */
function quoted(text: string): string {
  const t = displayQuote(text);
  return /^["“]/.test(t) ? t : `“${t}”`;
}

/** Every verified quote behind a citation (a compound claim can rest on two or three). */
function citationQuotes(c: Citation): string[] {
  const quotes = Array.isArray(c.quotes)
    ? (c.quotes as { quote?: unknown }[]).map((q) => (typeof q?.quote === "string" ? q.quote : "")).filter(Boolean)
    : [];
  if (quotes.length) return quotes.slice(0, 3);
  return typeof c.quote === "string" && c.quote ? [c.quote] : [];
}

// ── citation badge with hover preview ──────────────────────────────────────

function CitationBadge({ num, citation, onOpen }: { num: number; citation?: Citation; onOpen: () => void }) {
  const [hovered, setHovered] = useState(false);

  return (
    <span
      className="relative inline-block align-baseline"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        onClick={onOpen}
        data-testid={`chat-citation-${num}`}
        title={
          citation?.verified === false
            ? "Quote not confirmed in the document text"
            : citation?.support === "partial"
              ? "The cited text supports only part of this statement"
              : undefined
        }
        className={cn(
          "mx-0.5 inline-flex items-center gap-0.5 rounded px-1.5 py-0.2 font-mono text-[10.5px] font-semibold transition-colors cursor-pointer bg-amber-500/10 text-amber-800 dark:text-amber-300 hover:bg-amber-500/20 border border-amber-500/30",
          (citation?.verified === false || citation?.support === "partial") && "border-dashed opacity-80",
          !citation && "cursor-default opacity-60",
        )}
      >
        <span>[{num}]</span>
        {citation?.verified === false && <span aria-hidden>?</span>}
      </button>

      {/* Hover preview */}
      {hovered && citation && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 rounded-lg shadow-xl border border-border bg-popover text-popover-foreground text-left text-xs z-50 animate-in fade-in-0 zoom-in-95 pointer-events-auto">
          <span className="mb-1 block truncate font-semibold text-ink">
            {String(citation.title ?? citation.document_id ?? `Source [${num}]`)}
          </span>
          {typeof citation.quote === "string" && citation.quote && (
            <span className="mb-2 block rounded bg-secondary/50 p-1.5 text-[11px] italic text-muted-foreground line-clamp-3">
              {quoted(citation.quote)}
            </span>
          )}
          <button
            type="button"
            onClick={onOpen}
            className="w-full text-center py-1 rounded bg-primary text-primary-foreground font-medium text-[11px] hover:bg-primary/90 transition-colors flex items-center justify-center gap-1 cursor-pointer"
          >
            <span>View in document</span>
            <ArrowUpRight className="w-3 h-3" />
          </button>
        </span>
      )}
    </span>
  );
}

// ── composer ─────────────────────────────────────────────────────────────────

// What each work mode changes about the answer (see app/chat/system_prompt.py).
const MODES: { id: WorkMode; label: string; description: string }[] = [
  { id: "cite", label: "Cite", description: "Every statement quotes the passage it relies on." },
  { id: "reason", label: "Reason", description: "Explains which records it will use before answering." },
  { id: "research", label: "Research memo", description: "Legal position, authorities and analysis under headings." },
  { id: "review", label: "Risk review", description: "Table of issues in the documents, with suggested changes." },
];

function Composer({
  streaming,
  disabled,
  mode,
  onMode,
  uploading,
  attachments,
  draft,
  onRemoveAttachment,
  onDropPage,
  onOpenAttachment,
  onUpload,
  onPickDocuments,
  onSend,
  onStop,
}: {
  streaming: boolean;
  disabled: boolean;
  mode: WorkMode;
  onMode: (mode: WorkMode) => void;
  uploading: boolean;
  attachments: Attachment[];
  /** Text placed in the box by a starter card; `nonce` changes on every pick. */
  draft?: { text: string; nonce: number };
  onRemoveAttachment: (key: string) => void;
  /** A page dragged in from the document viewer. */
  onDropPage: (page: NonNullable<ReturnType<typeof readPageDrag>>) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  onUpload: (file: File) => void;
  onPickDocuments: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [dropping, setDropping] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const current = MODES.find((m) => m.id === mode) ?? MODES[0];

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  useEffect(() => {
    if (!draft) return;
    setText(draft.text);
    const el = ref.current;
    if (el) {
      el.focus();
      el.setSelectionRange(draft.text.length, draft.text.length);
    }
  }, [draft]);

  const submit = () => {
    if (!text.trim() || streaming || disabled) return;
    onSend(text);
    setText("");
  };

  return (
    <div className="border-t border-border/80 bg-background/90 px-4 pb-2 pt-3 lg:px-8">
      <div className="mx-auto max-w-3xl">
        <div
          data-testid="composer"
          onDragOver={(e) => {
            if (!hasPageDrag(e)) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = "copy";
            setDropping(true);
          }}
          onDragLeave={(e) => {
            if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setDropping(false);
          }}
          onDrop={(e) => {
            setDropping(false);
            const page = readPageDrag(e);
            if (!page) return;
            e.preventDefault();
            onDropPage(page);
            ref.current?.focus();
          }}
          className={cn(
            "flex flex-col rounded-2xl border border-border bg-card shadow-sm transition-all focus-within:border-wine/60 focus-within:ring-2 focus-within:ring-wine/10",
            dropping && "border-wine ring-2 ring-wine/30",
          )}
        >
          {dropping && (
            <p className="px-3 pt-2.5 text-xs font-medium text-wine" data-testid="composer-drop-hint">Drop the page to add it to this message</p>
          )}
          {(attachments.length > 0 || uploading) && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5" data-testid="composer-attachments">
              {attachments.map((a) => (
                <span
                  key={attachmentKey(a)}
                  data-testid="composer-attachment"
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/60 py-0.5 pl-1.5 pr-0.5 text-[11px] text-foreground"
                >
                  <button
                    type="button"
                    onClick={() => onOpenAttachment(a)}
                    title="Preview"
                    data-testid="composer-attachment-open"
                    className="inline-flex items-center gap-1 hover:underline"
                  >
                    <FileText className="h-3 w-3 text-amber-500" />
                    <span className="max-w-[200px] truncate">{attachmentLabel(a)}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${attachmentLabel(a)}`}
                    onClick={() => onRemoveAttachment(attachmentKey(a))}
                    className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {uploading && (
                <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
                  <Sparkles className="h-3 w-3 animate-spin" /> Filing and indexing…
                </span>
              )}
            </div>
          )}
          <textarea
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={disabled ? "The assistant is not available: no language model is set up." : "Ask about your matters or attached documents…"}
            disabled={disabled}
            aria-label="Message"
            data-testid="chat-input"
            className="max-h-[180px] w-full resize-none bg-transparent p-3.5 text-[14.5px] leading-relaxed text-ink placeholder:text-muted-foreground focus:outline-hidden"
          />

          <div className="flex items-center justify-between gap-2 rounded-b-2xl border-t border-border/60 bg-muted/30 px-2 py-1.5 text-xs">
            <div className="flex min-w-0 items-center gap-1">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  e.target.value = "";
                  if (file) onUpload(file);
                }}
              />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    title="Attach"
                    className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <Paperclip className="h-4 w-4" />
                    <span className="text-xs font-medium">Attach</span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-56">
                  <DropdownMenuItem disabled={uploading} onSelect={() => fileRef.current?.click()}>
                    <FileText className="mr-2 h-3.5 w-3.5 text-amber-500" />
                    {uploading ? "Filing document…" : "Upload a file"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onPickDocuments}>
                    <Search className="mr-2 h-3.5 w-3.5" />
                    Choose firm documents
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    data-testid="chat-mode"
                    title="How the answer is written"
                    className="flex min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <span className="text-xs">Mode:</span>
                    <span className="truncate text-xs font-semibold text-foreground">{current.label}</span>
                    <Icon name="expand_more" style={{ fontSize: 16 }} />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-72">
                  {MODES.map((m) => (
                    <DropdownMenuItem
                      key={m.id}
                      onSelect={() => onMode(m.id)}
                      data-testid={`chat-mode-${m.id}`}
                      className="flex items-start gap-2 py-2"
                    >
                      <Check className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", m.id === mode ? "text-wine" : "invisible")} />
                      <span>
                        <span className="block text-[13px] font-semibold text-foreground">{m.label}</span>
                        <span className="block text-[12px] text-muted-foreground">{m.description}</span>
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={onStop}
                data-testid="chat-stop"
                className="inline-flex items-center gap-1 rounded-xl bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground shadow-2xs hover:opacity-90"
              >
                <Icon name="stop" style={{ fontSize: 16 }} />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={!text.trim() || disabled}
                data-testid="chat-send"
                className="inline-flex items-center gap-1 rounded-xl bg-primary px-3.5 py-1.5 text-xs font-semibold text-primary-foreground shadow-2xs transition-colors hover:bg-primary/90 disabled:bg-secondary disabled:text-muted-foreground disabled:shadow-none"
              >
                <span>Send</span>
                <Icon name="arrow_upward" style={{ fontSize: 16 }} />
              </button>
            )}
          </div>
        </div>
        <p className="mt-1.5 flex items-center justify-center gap-1.5 text-center text-[11px] text-muted-foreground" data-testid="chat-review-note">
          <ShieldCheck className="h-3 w-3 shrink-0" />
          <span>
            Answers are AI-generated; check the cited sources before relying on them.
            <span className="hidden sm:inline"> Shift+Enter adds a new line.</span>
          </span>
        </p>
      </div>
    </div>
  );
}

// ── attach existing firm documents ────────────────────────────────────────────

function DocumentPicker({
  open,
  onOpenChange,
  selected,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selected: string[];
  onPick: (doc: DocumentItem) => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  const results = useQuery({
    queryKey: ["chat-doc-picker", debounced],
    queryFn: () =>
      apiFetch<Paged<DocumentItem>>(`/api/documents?limit=30${debounced ? `&q=${encodeURIComponent(debounced)}` : ""}`),
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col gap-0 p-0 sm:max-w-[420px]" data-testid="document-picker">
        <SheetHeader className="space-y-0 border-b border-border px-4 py-3 text-left">
          <SheetTitle className="font-display text-base text-ink">Attach firm documents</SheetTitle>
        </SheetHeader>
        <div className="relative border-b border-border px-4 py-2">
          <Search className="pointer-events-none absolute left-6 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, number or text…"
            aria-label="Search documents"
            data-testid="document-picker-search"
            className="w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-2 text-sm placeholder:text-muted-foreground focus:outline-hidden"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {results.isPending && <p className="px-2 py-1 text-xs text-muted-foreground">Searching…</p>}
          {results.data?.items.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">No documents match.</p>}
          {results.data?.items.map((d) => {
            const isOn = selected.includes(d.document_id);
            return (
              <button
                key={d.document_id}
                type="button"
                disabled={isOn}
                onClick={() => onPick(d)}
                data-testid="document-picker-item"
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-secondary disabled:opacity-60"
              >
                <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-amber-500" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-ink">{d.title}</span>
                  <span className="block truncate font-mono text-[10.5px] text-muted-foreground">
                    {d.document_id} · {d.matter_code ?? d.matter_id ?? ""}
                  </span>
                </span>
                {isOn && <Check className="mt-0.5 h-3.5 w-3.5 text-emerald-600" />}
              </button>
            );
          })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
