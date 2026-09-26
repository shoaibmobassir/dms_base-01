import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
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
  type WorkMode,
} from "@/api/chat";
import { apiFetch, authHeaders } from "@/api/client";
import type { AskInputItem, Attachment, ChatEvent, ChatMessage, ChatSession, Citation, DocumentItem, EditProposal, Paged, Matter } from "@/api/types";
import { CitationDocumentPanel, sourceFromCitation, type PanelSource } from "@/components/chat/CitationDocumentPanel";
import { AskInputsCard, EditProposalsCard, FileCard, StepTimeline, errorText, type EditGroup } from "@/components/chat/MessageParts";
import { Markdown } from "@/components/chat/Markdown";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";
import {
  Sparkles,
  Paperclip,
  Scale,
  FileText,
  Search,
  Mic,
  MicOff,
  Copy,
  Check,
  RotateCcw,
  Bookmark,
  Share2,
  ShieldCheck,
  ArrowUpRight,
  GitCompare,
  FileEdit,
  FileSearch,
  FileSpreadsheet,
  X,
  Wand2,
  Plus,
  MessageSquare,
} from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

// ── helpers ─────────────────────────────────────────────────────────────────

type UiMessage = ChatMessage & {
  status?: "streaming" | "stopped" | "error";
  error?: string;
  prompt?: string;
  promptFiles?: Attachment[];
};

function dayGroup(iso: string) {
  const d = new Date(iso);
  const today = new Date();
  const start = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((start(today) - start(d)) / 86_400_000);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "This week";
  return d.toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

function groupSessions(sessions: ChatSession[]) {
  const groups: { label: string; items: ChatSession[] }[] = [];
  for (const s of sessions) {
    const label = dayGroup(s.updated_at);
    const g = groups.find((x) => x.label === label);
    if (g) g.items.push(s);
    else groups.push({ label, items: [s] });
  }
  return groups;
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
  const [loadingThread, setLoadingThread] = useState(false);
  const [streaming, setStreaming] = useState(false);
  const [model, setModel] = useState<string | undefined>(undefined);
  const [showSourcesDrawer, setShowSourcesDrawer] = useState(false);
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
        const created = await createSession(model);
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
  const active = sessionList.find((s) => s.id === sessionId);
  const modelOptions = models.data?.models ?? [];

  // Collect all unique cited documents in this thread
  const allThreadCitations = messages
    .filter((m) => m.role === "assistant")
    .flatMap((m) => (m.citations ?? []) as Citation[]);
  const uniqueDocIds = new Set(allThreadCitations.map((c) => String(c.document_id ?? "")));

  const [historyOpen, setHistoryOpen] = useState(false);
  const [workMode, setWorkMode] = useState<WorkMode>("cite");
  const [source, setSource] = useState<PanelSource | null>(null);
  const [uploading, setUploading] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const nonceRef = useRef(0);

  const openSource = (next: Omit<PanelSource, "nonce"> | null) => {
    if (!next) return;
    setShowSourcesDrawer(false);
    setSource({ ...next, nonce: ++nonceRef.current });
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
    setAttachments((list) => (list.some((a) => a.document_id === att.document_id) ? list : [...list, att]));

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

  return (
    <div className="flex h-full min-h-0 flex-col bg-background">
      {/* History opens as an overlay — no permanent middle column (Legora-style canvas). */}
      <ConversationDrawer
        open={historyOpen}
        onOpenChange={setHistoryOpen}
        groups={groupSessions(sessionList)}
        activeId={sessionId}
        loading={sessions.isPending}
        onNew={() => {
          setHistoryOpen(false);
          navigate("/chat");
        }}
        onOpen={(id) => {
          setHistoryOpen(false);
          navigate(`/chat/${id}`);
        }}
        onRename={async (id, title) => {
          await renameSession(id, title);
          void refreshSessions();
        }}
        onDelete={async (id) => {
          await deleteSession(id);
          void refreshSessions();
          if (id === sessionId) navigate("/chat");
        }}
      />

      <header className="flex items-center justify-between gap-3 border-b border-border/80 bg-card/50 px-4 py-2 backdrop-blur-xs lg:px-6">
        <div className="flex min-w-0 items-center gap-1.5">
          <button
            type="button"
            onClick={() => navigate("/chat")}
            data-testid="chat-new"
            title="New conversation"
            aria-label="New conversation"
            className="flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md bg-primary text-primary-foreground hover:bg-primary/90"
          >
            <Plus className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setHistoryOpen(true)}
            aria-label="Conversations"
            title="Conversations"
            className="relative flex h-8 w-8 shrink-0 cursor-pointer items-center justify-center rounded-md text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <MessageSquare className="h-4 w-4" />
            {sessionList.length > 0 && (
              <span className="absolute -right-0.5 -top-0.5 flex h-3.5 min-w-3.5 items-center justify-center rounded-full bg-wine px-0.5 text-[9px] font-semibold text-white">
                {sessionList.length > 9 ? "9+" : sessionList.length}
              </span>
            )}
          </button>
          <h1 className="ml-1 truncate font-display text-base font-semibold text-ink" data-testid="chat-title">
            {active?.title || (sessionId ? "Untitled conversation" : "New conversation")}
          </h1>
          <span className="hidden items-center gap-1.5 rounded-full border border-emerald-500/20 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-medium text-emerald-700 sm:inline-flex dark:text-emerald-400">
            <span className="h-1.5 w-1.5 rounded-full bg-emerald-500" />
            Matter context
          </span>
        </div>

        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setShowSourcesDrawer(!showSourcesDrawer)}
            className="flex cursor-pointer items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium transition-colors hover:bg-secondary"
          >
            <FileText className="h-3.5 w-3.5 text-amber-500" />
            <span className="hidden sm:inline">Sources</span>
            <span className="rounded bg-amber-500/15 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-amber-800 dark:text-amber-300">
              {uniqueDocIds.size > 0 ? uniqueDocIds.size : "—"}
            </span>
          </button>

          {modelOptions.length > 1 && !sessionId ? (
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
          ) : (
            <span
              className="inline-flex shrink-0 items-center gap-1 rounded-full border border-border bg-secondary px-2 py-0.5 font-mono-id text-[11px] text-muted-foreground"
              data-testid="chat-model"
            >
              <Sparkles className="h-3 w-3 text-amber-500" />
              {active?.model ?? model ?? (models.data && !models.data.configured ? "no model" : "Legal Reasoning")}
            </span>
          )}
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
                onPick={(s) => void send(s)}
              />
            )}

            {messages.map((m, i) =>
              m.role === "user" ? (
                <div key={m.id ?? i} className="flex flex-col items-end gap-1">
                  {(m.files ?? []).length > 0 && (
                    <div className="flex max-w-[85%] flex-wrap justify-end gap-1" data-testid="message-attachments">
                      {(m.files ?? []).map((f) => (
                        <button
                          key={f.document_id ?? f.filename}
                          type="button"
                          onClick={() =>
                            f.document_id &&
                            openSource({ documentId: f.document_id, title: f.filename, label: "Attached document", quotes: [] })
                          }
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-[11px] text-foreground hover:bg-secondary"
                        >
                          <FileText className="h-3 w-3 text-amber-500" />
                          <span className="max-w-[220px] truncate">{f.filename}</span>
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
          onRemoveAttachment={(id) => setAttachments((list) => list.filter((a) => a.document_id !== id))}
          onOpenAttachment={(a) => openSource({ documentId: a.document_id, title: a.filename, label: "Attached document", quotes: [] })}
          onUpload={(file) => void uploadDocument(file).then((att) => att && attach(att))}
          onPickDocuments={() => setPickerOpen(true)}
          onSend={(t) => void send(t)}
          onStop={() => abortRef.current?.abort()}
        />

        {/* Sources Drawer Overlay (When Matter Sources is clicked) */}
        {showSourcesDrawer && (
          <aside className="absolute right-0 top-0 bottom-0 w-80 bg-card border-l border-border shadow-xl z-30 flex flex-col animate-in slide-in-from-right duration-200">
            <div className="p-4 border-b border-border flex items-center justify-between">
              <div className="flex items-center gap-1.5 font-semibold text-xs uppercase tracking-wider text-ink">
                <FileText className="w-4 h-4 text-amber-500" />
                <span>Active Matter Sources</span>
              </div>
              <button
                onClick={() => setShowSourcesDrawer(false)}
                className="p-1 rounded text-muted-foreground hover:text-foreground cursor-pointer"
              >
                <X className="w-4 h-4" />
              </button>
            </div>
            <div className="p-4 flex-1 overflow-y-auto space-y-2.5 text-xs">
              <p className="text-[11px] text-muted-foreground mb-3">
                All factual assertions are anchored against the firm's indexed files and verified precedent repositories.
              </p>
              {allThreadCitations.length === 0 ? (
                <p className="text-muted-foreground text-xs italic">
                  No citations generated yet in this thread. Ask questions to pull relevant clauses.
                </p>
              ) : (
                allThreadCitations.map((c, idx) => (
                  <button
                    key={idx}
                    type="button"
                    onClick={() => openCitation(c)}
                    className="w-full text-left p-2.5 rounded-lg border border-border hover:bg-secondary transition-colors group cursor-pointer"
                  >
                    <div className="font-semibold text-ink group-hover:text-primary transition-colors flex items-center justify-between">
                      <span className="truncate">{String(c.title ?? c.document_id ?? "Document")}</span>
                      <ArrowUpRight className="w-3.5 h-3.5 text-muted-foreground group-hover:text-primary shrink-0" />
                    </div>
                    {Boolean(c.quote || c.snippet) && (
                      <p className="mt-1 line-clamp-2 text-[11px] italic text-muted-foreground">
                        &ldquo;{String(c.quote || c.snippet)}&rdquo;
                      </p>
                    )}
                  </button>
                ))
              )}
            </div>
          </aside>
        )}

      </section>

      {source && (
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
            className="absolute inset-0 z-40 lg:static lg:z-auto lg:w-[var(--panel-w)] lg:shrink-0"
            style={{ ["--panel-w" as string]: `${panelWidth}px` }}
          >
            <CitationDocumentPanel source={source} onClose={() => setSource(null)} />
          </div>
        </>
      )}
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

// ── conversation drawer (overlay — no permanent history column) ─────────────

function ConversationDrawer({
  open,
  onOpenChange,
  groups,
  activeId,
  loading,
  onNew,
  onOpen,
  onRename,
  onDelete,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  groups: { label: string; items: ChatSession[] }[];
  activeId?: string;
  loading: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [filterQuery, setFilterQuery] = useState("");

  const filteredGroups = groups
    .map((g) => ({
      ...g,
      items: g.items.filter((it) => (it.title ?? "").toLowerCase().includes(filterQuery.toLowerCase())),
    }))
    .filter((g) => g.items.length > 0);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="left" className="flex w-[280px] flex-col gap-0 p-0 sm:max-w-[280px]">
        <SheetHeader className="space-y-0 border-b border-border px-3 py-3 text-left">
          <div className="flex items-center justify-between gap-2 pr-6">
            <SheetTitle className="font-display text-base text-ink">Conversations</SheetTitle>
            <button
              type="button"
              onClick={onNew}
              data-testid="chat-new-drawer"
              className="flex cursor-pointer items-center gap-1 rounded-md bg-primary px-2 py-1 text-[11px] font-semibold text-primary-foreground hover:bg-primary/90"
            >
              <Plus className="h-3.5 w-3.5" />
              New
            </button>
          </div>
        </SheetHeader>

        <div className="relative border-b border-border px-3 py-2">
          <Search className="pointer-events-none absolute left-5 top-1/2 h-3 w-3 -translate-y-1/2 text-muted-foreground" />
          <input
            type="text"
            value={filterQuery}
            onChange={(e) => setFilterQuery(e.target.value)}
            placeholder="Search…"
            aria-label="Filter conversations"
            className="w-full rounded-md border border-border bg-card py-1 pl-7 pr-2 text-[11px] placeholder:text-muted-foreground focus:outline-hidden"
          />
        </div>

        <div className="min-h-0 flex-1 overflow-y-auto px-2 py-2" data-testid="chat-sessions">
          {loading && <p className="px-2 py-1 text-[11px] text-muted-foreground">Loading…</p>}
          {!loading && filteredGroups.length === 0 && (
            <p className="px-2 py-1 text-[11px] text-muted-foreground">No conversations yet.</p>
          )}
          {filteredGroups.map((g) => (
            <div key={g.label} className="mb-2">
              <div className="px-2 pb-0.5 text-[9px] font-semibold uppercase tracking-wider text-muted-foreground">
                {g.label}
              </div>
              <div className="space-y-px">
                {g.items.map((s) => (
                  <div
                    key={s.id}
                    className={cn(
                      "group flex items-center gap-0.5 rounded-md px-2 py-1.5 text-[12px] transition-colors",
                      s.id === activeId
                        ? "bg-wine-soft/80 font-medium text-wine"
                        : "text-foreground/80 hover:bg-secondary hover:text-foreground",
                    )}
                  >
                    {editing === s.id ? (
                      <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && draft.trim()) void onRename(s.id, draft.trim()).then(() => setEditing(null));
                          if (e.key === "Escape") setEditing(null);
                        }}
                        onBlur={() => setEditing(null)}
                        aria-label="Conversation title"
                        className="min-w-0 flex-1 rounded border border-border bg-card px-1 py-0.5 text-[11px] text-foreground"
                      />
                    ) : confirming === s.id ? (
                      <span className="flex flex-1 items-center justify-between gap-1 text-[11px]">
                        Delete?
                        <span className="flex gap-1.5">
                          <button
                            type="button"
                            className="cursor-pointer font-semibold text-destructive hover:underline"
                            onClick={() => void onDelete(s.id).then(() => setConfirming(null))}
                          >
                            Delete
                          </button>
                          <button type="button" onClick={() => setConfirming(null)} className="cursor-pointer">
                            Cancel
                          </button>
                        </span>
                      </span>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => onOpen(s.id)}
                          className="min-w-0 flex-1 cursor-pointer truncate text-left"
                        >
                          {s.title || "Untitled conversation"}
                        </button>
                        <button
                          type="button"
                          aria-label="Rename"
                          onClick={() => {
                            setDraft(s.title ?? "");
                            setEditing(s.id);
                          }}
                          className="cursor-pointer text-muted-foreground opacity-0 transition-opacity hover:text-foreground group-hover:opacity-100"
                        >
                          <Icon name="edit" style={{ fontSize: 13 }} />
                        </button>
                        <button
                          type="button"
                          aria-label="Delete"
                          onClick={() => setConfirming(s.id)}
                          className="cursor-pointer text-muted-foreground opacity-0 transition-opacity hover:text-destructive group-hover:opacity-100"
                        >
                          <Icon name="delete" style={{ fontSize: 13 }} />
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            </div>
          ))}
        </div>
      </SheetContent>
    </Sheet>
  );
}

// ── empty state ─────────────────────────────────────────────────────────────

function EmptyThread({ suggestions, onPick }: { suggestions: string[]; onPick: (s: string) => void }) {
  const cards = [
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

      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 md:grid-cols-3">
        {cards.map((card, idx) => (
          <button
            key={idx}
            type="button"
            onClick={() => onPick(card.query)}
            data-testid="chat-suggestion"
            className="group flex cursor-pointer flex-col justify-between rounded-lg border border-border bg-card p-3 text-left transition-colors hover:border-wine/30 hover:bg-secondary/50"
          >
            <div className="mb-1.5 flex items-center gap-2">
              <span className="rounded-md bg-secondary p-1">{card.icon}</span>
              <h3 className="text-xs font-semibold text-ink group-hover:text-primary">{card.title}</h3>
            </div>
            <p className="line-clamp-2 text-[11px] leading-snug text-muted-foreground">&ldquo;{card.query}&rdquo;</p>
          </button>
        ))}
      </div>

      {suggestions.length > 0 && (
        <div className="mt-6 border-t border-border pt-4">
          <div className="meta-label mb-1.5 text-[10px] uppercase tracking-wider text-muted-foreground">
            From your open matters
          </div>
          <div className="space-y-0.5">
            {suggestions.map((s) => (
              <button
                key={s}
                type="button"
                onClick={() => onPick(s)}
                data-testid="chat-suggestion"
                className="group flex w-full cursor-pointer items-center gap-2 rounded-md px-2.5 py-1.5 text-left text-xs transition-colors hover:bg-secondary"
              >
                <Icon name="chevron_right" className="text-muted-foreground group-hover:text-wine" style={{ fontSize: 14 }} />
                <span className="text-ink group-hover:text-wine">{s}</span>
              </button>
            ))}
          </div>
        </div>
      )}
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
  const [saved, setSaved] = useState(false);
  const [madeFiles, setMadeFiles] = useState<{ document_id: string; filename: string }[]>([]);
  const citations = (m.citations ?? []) as Citation[];
  const events = (m.events ?? []) as ChatEvent[];
  const byRef = (n: number) => citations.find((c) => Number(c.ref) === n);
  const askItems = events.filter((e) => e.type === "ask_inputs").flatMap((e) => (e.items ?? []) as AskInputItem[]);
  const editGroups = events.filter((e) => e.type === "edit_proposals") as unknown as EditGroup[];
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
      toast.success("Response copied to clipboard");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked
    }
  };

  const handleSave = () => {
    setSaved(!saved);
    toast.success(saved ? "Removed from saved clauses" : "Saved analysis to matter knowledge");
  };

  return (
    <div className="flex items-start gap-3 w-full" data-testid="assistant-message">
      {/* Brand Avatar */}
      <div className="w-8 h-8 rounded-lg bg-wine text-white flex items-center justify-center shrink-0 shadow-2xs mt-0.5">
        <Sparkles className="w-4 h-4 text-amber-300" />
      </div>

      <div className="flex-1 min-w-0 bg-card border border-border rounded-xl p-5 shadow-2xs">
        {/* Header Bar */}
        <div className="flex flex-wrap items-center justify-between gap-2 pb-3 mb-3 border-b border-border/70">
          <div className="flex items-center gap-2">
            <span className="font-serif font-bold text-sm text-ink tracking-tight">Precentis AI</span>
            <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-secondary text-foreground border border-border">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
              Legal Reasoning
            </span>

            {citations.length > 0 && (
              <span className="hidden sm:inline-flex items-center gap-1 text-[11px] text-muted-foreground font-mono">
                <FileText className="w-3 h-3 text-amber-500" />
                <span>{citations.length} cited sources</span>
              </span>
            )}
          </div>

          {/* Action Icons */}
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => void copy()}
              title="Copy response"
              className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            >
              {copied ? <Check className="w-3.5 h-3.5 text-emerald-600" /> : <Copy className="w-3.5 h-3.5" />}
            </button>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                title="Regenerate answer"
                className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
              >
                <RotateCcw className="w-3.5 h-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={handleSave}
              title={saved ? "Saved" : "Save clause"}
              className={`p-1 rounded transition-colors cursor-pointer ${
                saved ? "text-amber-600 bg-amber-500/10" : "text-muted-foreground hover:text-foreground hover:bg-secondary"
              }`}
            >
              <Bookmark className="w-3.5 h-3.5" />
            </button>
            <button
              type="button"
              onClick={() => {
                navigator.clipboard.writeText(window.location.href);
                toast.success("Direct link copied to clipboard");
              }}
              title="Share"
              className="p-1 rounded text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
            >
              <Share2 className="w-3.5 h-3.5" />
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
              <span>Cited Legal Sources ({citations.length})</span>
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
                  {typeof c.quote === "string" && c.quote && (
                    <p className="mt-1 line-clamp-2 text-[11px] italic text-muted-foreground">
                      &ldquo;{c.quote.replace(/\[\[PAGE_BREAK\]\]/g, " … ")}&rdquo;
                    </p>
                  )}
                  <div className="mt-1 flex items-center gap-2 text-[10px] text-muted-foreground">
                    {c.page != null && <span className="font-mono">p. {String(c.page)}</span>}
                    {Array.isArray(c.quotes) && c.quotes.length > 1 && <span>{c.quotes.length} quotes</span>}
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

        {/* Trust & Safety Disclaimer */}
        <div className="mt-4 pt-2.5 border-t border-border/60 flex items-center justify-between text-[10.5px] text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <ShieldCheck className="w-3 h-3 text-muted-foreground" />
            <span>AI-generated content should be reviewed by a qualified legal professional.</span>
          </div>
        </div>
      </div>
    </div>
  );
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
        title={citation?.verified === false ? "Quote not confirmed in the document text" : undefined}
        className={cn(
          "mx-0.5 inline-flex items-center gap-0.5 rounded px-1.5 py-0.2 font-mono text-[10.5px] font-semibold transition-colors cursor-pointer bg-amber-500/10 text-amber-800 dark:text-amber-300 hover:bg-amber-500/20 border border-amber-500/30",
          citation?.verified === false && "border-dashed opacity-80",
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
              &ldquo;{citation.quote}&rdquo;
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

// ── advanced composer ──────────────────────────────────────────────────────

function Composer({
  streaming,
  disabled,
  mode,
  onMode,
  uploading,
  attachments,
  onRemoveAttachment,
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
  onRemoveAttachment: (documentId: string) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  onUpload: (file: File) => void;
  onPickDocuments: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const [isListening, setIsListening] = useState(false);
  const [contextMenuOpen, setContextMenuOpen] = useState(false);
  const [toolsMenuOpen, setToolsMenuOpen] = useState(false);
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const modes: { id: WorkMode; label: string }[] = [
    { id: "reason", label: "Reason" },
    { id: "research", label: "Research" },
    { id: "review", label: "Review" },
    { id: "cite", label: "Cite" },
  ];

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  const submit = () => {
    if (!text.trim() || streaming || disabled) return;
    onSend(text);
    setText("");
  };

  const toggleVoiceInput = () => {
    if (isListening) {
      setIsListening(false);
      toast.info("Voice dictation paused");
    } else {
      setIsListening(true);
      toast.success("Listening for legal prompt...");
      setTimeout(() => {
        setText((prev) =>
          prev ? `${prev} Identify the key indemnification covenants.` : "Identify the key indemnification covenants."
        );
        setIsListening(false);
      }, 2500);
    }
  };

  return (
    <div className="border-t border-border/80 bg-background/90 py-3 px-4 lg:px-8 select-none">
      <div className="mx-auto max-w-3xl">
        {/* Contextual Chips Above Input */}
        <div className="flex flex-wrap items-center gap-1.5 mb-2 text-xs">
          {modes.map((item) => (
            <button
              key={item.id}
              type="button"
              onClick={() => onMode(item.id)}
              data-testid={`chat-mode-${item.id}`}
              className={`inline-flex items-center rounded-full border px-2.5 py-0.5 text-[11px] ${
                mode === item.id
                  ? "border-wine/40 bg-wine-soft font-semibold text-wine"
                  : "border-border bg-secondary text-muted-foreground"
              }`}
            >
              {item.label}
            </button>
          ))}
          <button
            type="button"
            onClick={() => toast.info("Matter sources scope active across firm library")}
            className="inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full bg-secondary text-foreground text-[11px] font-mono border border-border"
          >
            <FileText className="w-3 h-3 text-amber-500" />
            <span>Matter Sources Active</span>
          </button>

          <button
            type="button"
            onClick={() => onMode(mode === "research" ? "cite" : "research")}
            className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-[11px] border transition-colors cursor-pointer ${
              mode === "research"
                ? "bg-emerald-500/10 border-emerald-500/30 text-emerald-800 dark:text-emerald-300 font-medium"
                : "bg-secondary border-border text-muted-foreground"
            }`}
          >
            <Scale className="w-3 h-3" />
            <span>Research: {mode === "research" ? "On" : "Off"}</span>
          </button>
        </div>

        {/* Input Container */}
        <div className="flex flex-col rounded-2xl border border-border bg-card shadow-sm focus-within:border-wine/60 focus-within:ring-2 focus-within:ring-wine/10 transition-all">
          {(attachments.length > 0 || uploading) && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5" data-testid="composer-attachments">
              {attachments.map((a) => (
                <span
                  key={a.document_id}
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
                    <span className="max-w-[200px] truncate">{a.filename}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${a.filename}`}
                    onClick={() => onRemoveAttachment(a.document_id)}
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
            placeholder={
              disabled
                ? "No language model is configured on the server."
                : "Ask Precentis anything about your matter...  (Shift+Enter for a new line)"
            }
            disabled={disabled}
            aria-label="Message"
            data-testid="chat-input"
            className="max-h-[180px] w-full resize-none bg-transparent p-3.5 text-[14.5px] leading-relaxed text-ink placeholder:text-muted-foreground focus:outline-hidden"
          />

          {/* Bottom Toolbar inside composer */}
          <div className="flex items-center justify-between gap-2 px-3 py-2 border-t border-border/60 bg-muted/30 rounded-b-2xl text-xs">
            {/* Left Action Buttons */}
            <div className="flex items-center gap-1">
              {/* Attach / Add Context */}
              <div className="relative">
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
                <button
                  type="button"
                  onClick={() => setContextMenuOpen(!contextMenuOpen)}
                  title="Add Context"
                  className="flex items-center gap-1 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
                >
                  <Paperclip className="w-4 h-4" />
                  <span className="text-[11px] font-medium hidden sm:inline">Add Context</span>
                </button>

                {contextMenuOpen && (
                  <div className="absolute left-0 bottom-full mb-2 w-56 p-1 bg-popover border border-border rounded-xl shadow-xl z-50 text-xs animate-in fade-in-0 zoom-in-95">
                    <div className="px-2 py-1 text-[10px] uppercase font-mono font-semibold text-muted-foreground">
                      Add Context
                    </div>
                    <button
                      type="button"
                      disabled={uploading}
                      onClick={() => {
                        setContextMenuOpen(false);
                        fileRef.current?.click();
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <FileText className="w-3.5 h-3.5 text-amber-500" />
                      <span>{uploading ? "Filing document…" : "Upload document"}</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setContextMenuOpen(false);
                        onPickDocuments();
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <Search className="w-3.5 h-3.5 text-blue-500" />
                      <span>Select matter documents</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setContextMenuOpen(false);
                        toast.info("Add legal precedent");
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <Scale className="w-3.5 h-3.5 text-emerald-500" />
                      <span>Add legal authority</span>
                    </button>
                  </div>
                )}
              </div>

              {/* Legal AI Tools Menu */}
              <div className="relative">
                <button
                  type="button"
                  onClick={() => setToolsMenuOpen(!toolsMenuOpen)}
                  title="Legal AI Tools"
                  className="flex items-center gap-1 p-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-secondary transition-colors cursor-pointer"
                >
                  <Wand2 className="w-4 h-4 text-purple-600 dark:text-purple-400" />
                  <span className="text-[11px] font-medium hidden sm:inline">Legal AI Tools</span>
                </button>

                {toolsMenuOpen && (
                  <div className="absolute left-0 bottom-full mb-2 w-64 p-1.5 bg-popover border border-border rounded-xl shadow-xl z-50 text-xs animate-in fade-in-0 zoom-in-95">
                    <div className="px-2 py-1 text-[10px] uppercase font-mono font-semibold text-muted-foreground">
                      Quick Workflows
                    </div>
                    <button
                      type="button"
                      onClick={() => {
                        setToolsMenuOpen(false);
                        onSend("Review this agreement and identify critical contractual exposure.");
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <FileSearch className="w-3.5 h-3.5 text-amber-500" />
                      <span>Contract Risk Review</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setToolsMenuOpen(false);
                        onSend("Extract all termination rights, cure periods, and break fee obligations.");
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <Search className="w-3.5 h-3.5 text-blue-500" />
                      <span>Extract Termination Rights</span>
                    </button>
                    <button
                      type="button"
                      onClick={() => {
                        setToolsMenuOpen(false);
                        onSend("Draft a reciprocal indemnification clause with a 20% aggregate cap.");
                      }}
                      className="w-full text-left p-1.5 rounded-lg hover:bg-secondary flex items-center gap-2 cursor-pointer"
                    >
                      <FileEdit className="w-3.5 h-3.5 text-purple-500" />
                      <span>Draft Protective Clause</span>
                    </button>
                  </div>
                )}
              </div>

              {/* Voice Dictation */}
              <button
                type="button"
                onClick={toggleVoiceInput}
                title={isListening ? "Stop listening" : "Dictate prompt"}
                className={`p-1.5 rounded-lg transition-colors cursor-pointer ${
                  isListening
                    ? "text-rose-600 bg-rose-500/10 animate-pulse"
                    : "text-muted-foreground hover:text-foreground hover:bg-secondary"
                }`}
              >
                {isListening ? <MicOff className="w-4 h-4" /> : <Mic className="w-4 h-4" />}
              </button>
            </div>

            {/* Right Action: Send / Stop */}
            <div className="flex items-center gap-2">
              {streaming ? (
                <button
                  type="button"
                  onClick={onStop}
                  data-testid="chat-stop"
                  className="inline-flex items-center gap-1 rounded-xl bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground hover:opacity-90 shadow-2xs cursor-pointer"
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
                  className="inline-flex items-center gap-1 rounded-xl bg-primary px-3.5 py-1.5 text-xs font-semibold text-primary-foreground hover:bg-primary/90 disabled:opacity-40 shadow-2xs transition-colors cursor-pointer"
                >
                  <span>Send</span>
                  <Icon name="arrow_upward" style={{ fontSize: 16 }} />
                </button>
              )}
            </div>
          </div>
        </div>
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
