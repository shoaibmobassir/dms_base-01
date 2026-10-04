import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { useNavigate, useParams, useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { type WorkMode, createSession, deleteSession, getSession, listModels, listSessions, listSuggestions, renameSession, streamMessage, updateSession } from "@/api/chat";
import type { Attachment, ChatSession, Citation } from "@/api/types";
import { CitationDocumentPanel, type PanelSource, sourceFromCitation } from "@/components/chat/CitationDocumentPanel";
import { HistoryPane } from "@/components/chat/HistoryPane";
import { type MatterChoice, MatterScopePicker } from "@/components/chat/MatterScopePicker";
import type { MatterOption } from "@/components/common/MatterPicker";
import { fileProblem, uploadToMatter } from "@/api/uploads";
import { useMatter } from "@/api/resources";
import { errorText } from "@/components/chat/MessageParts";
import { Icon } from "@/components/common/primitives";
import { downloadFile } from "@/api/client";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useApp } from "@/context/AppContext";
import { useMediaQuery } from "@/lib/use-media-query";
import { conversationAsMarkdown, downloadText, safeFilename } from "@/lib/exportConversation";
import { cn } from "@/lib/utils";
import { FileText, History, Plus, Sparkles, X } from "lucide-react";
import { toast } from "sonner";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import type { UiMessage } from "@/components/chat/chatTypes";
import { ThreadSources } from "@/components/chat/ThreadSources";
import { EmptyThread } from "@/components/chat/EmptyThread";
import { AssistantMessage } from "@/components/chat/AssistantMessage";
import { Composer } from "@/components/chat/Composer";
import { DocumentPicker } from "@/components/chat/DocumentPicker";
import { MatterForUpload } from "@/components/chat/MatterForUpload";

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
    stickRef.current = true;
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

  // Follow the answer only while the reader is at the bottom; scrolling up to read stops it.
  const stickRef = useRef(true);
  const [showJump, setShowJump] = useState(false);
  const onThreadScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const near = el.scrollHeight - el.scrollTop - el.clientHeight < 80;
    stickRef.current = near;
    setShowJump(!near);
  };
  const jumpToLatest = () => {
    stickRef.current = true;
    setShowJump(false);
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  };
  useLayoutEffect(() => {
    if (stickRef.current) scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight });
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
    stickRef.current = true;

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
      { role: "user", content, files: sentFiles, created_at: new Date().toISOString() },
      { role: "assistant", content: "", events: [], citations: [], status: "streaming", prompt: content, promptFiles: sentFiles, created_at: new Date().toISOString() },
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

  // Editing the last message: the answer to it is dropped and the new wording is sent.
  const [editingAt, setEditingAt] = useState<number | null>(null);
  const [editText, setEditText] = useState("");
  const resend = (text: string, files: Attachment[]) => {
    setEditingAt(null);
    setMessages((prev) => prev.slice(0, -2));
    void send(text, files);
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
  // Ask the Firm hands a question over with ?q= (and usually ?matter=): pre-fill it, never auto-send.
  const handedQuestion = searchParams.get("q");
  const handedSend = searchParams.get("send") === "1";
  // A document page hands over the document to work on (?doc=&docTitle=): it arrives attached.
  const handedDocs = searchParams.getAll("doc");
  const handedDocTitles = searchParams.getAll("docTitle");
  const handedKey = handedDocs.join(",");
  // A question typed on a document page (?send=1) is sent at once, with that document attached and the
  // conversation limited to its matter. The values are read once: opening the matter clears the URL.
  const handed = useRef({
    q: searchParams.get("q"),
    send: searchParams.get("send") === "1",
    matter: searchParams.get("matter"),
    files: searchParams.getAll("doc").map((id, i) => ({ document_id: id, filename: searchParams.getAll("docTitle")[i] || id })),
  });
  const sentHanded = useRef(false);
  useEffect(() => {
    const h = handed.current;
    if (!h.send || !h.q || sentHanded.current || sessionId) return;
    if (h.matter && !pendingMatter) return; // wait for the matter to load
    sentHanded.current = true;
    void send(h.q, h.files);
    setAttachments([]); // they travel with the message; the box starts empty
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pendingMatter, sessionId]);
  useEffect(() => {
    if (!handedQuestion || handedSend) return;
    setDraft({ text: handedQuestion, nonce: Date.now() });
    if (!matterParam) setSearchParams({}, { replace: true });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handedQuestion]);

  useEffect(() => {
    if (handedDocs.length === 0) return;
    setAttachments((list) => {
      const next = [...list];
      handedDocs.forEach((id, i) => {
        if (!next.some((a) => a.document_id === id)) next.push({ document_id: id, filename: handedDocTitles[i] || id });
      });
      return next;
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [handedKey]);

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
    setAttachments((list) => (list.some((a) => a.document_id === att.document_id) ? list : [...list, att]));

  // A document is never filed into a matter by default: use the conversation's matter, or ask.
  const [matterPrompt, setMatterPrompt] = useState<{ resolve: (m: MatterOption | null) => void } | null>(null);
  const promptRef = useRef<Promise<MatterOption | null> | null>(null);
  const chooseMatter = () => {
    if (!promptRef.current) {
      promptRef.current = new Promise<MatterOption | null>((resolve) =>
        setMatterPrompt({
          resolve: (m) => {
            promptRef.current = null;
            setMatterPrompt(null);
            resolve(m);
          },
        }),
      );
    }
    return promptRef.current;
  };

  /** File an uploaded document in the conversation's matter (asking which one if there is none), index it, and return it as an attachment. */
  const uploadDocument = async (file: File): Promise<Attachment | null> => {
    const problem = fileProblem(file);
    if (problem) {
      toast.error(`${file.name}: ${problem}`);
      return null;
    }
    let matterId = active?.matter_id ?? pendingMatter?.matter_id ?? null;
    let matterCode = pendingMatter?.matter_code ?? "";
    if (!matterId) {
      const chosen = await chooseMatter();
      if (!chosen) return null;
      matterId = chosen.matter_id;
      matterCode = chosen.matter_code;
    }
    setUploading(true);
    try {
      const [outcome] = await uploadToMatter(matterId, [file]);
      if (outcome.status === "failed" || !outcome.documentId) throw new Error(outcome.error || "The document could not be indexed.");
      toast.success(
        outcome.status === "duplicate"
          ? `${file.name} is already in the firm's records and is attached.`
          : `${file.name} is filed${matterCode ? ` to ${matterCode}` : ""} and attached.`,
      );
      return { filename: file.name, document_id: outcome.documentId, content_type: file.type || undefined };
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

  const empty = !loadingThread && messages.length === 0;
  const composerEl = (
    <Composer
          hero={empty}
          leading={
            <>
              <MatterScopePicker
                matterId={active?.matter_id}
                pending={sessionId ? null : pendingMatter}
                onChange={(choice) => void changeScope(choice)}
                disabled={streaming}
              />
              {modelOptions.length > 1 && !sessionId && (
                <select
                  value={model}
                  onChange={(e) => setModel(e.target.value)}
                  aria-label="Model"
                  className="h-9 cursor-pointer rounded-full border border-border bg-card px-3 text-xs font-medium text-foreground focus:outline-none"
                >
                  {modelOptions.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </select>
              )}
            </>
          }
          streaming={streaming}
          disabled={models.data ? !models.data.configured : false}
          mode={workMode}
          onMode={setWorkMode}
          uploading={uploading}
          attachments={attachments}
          draft={draft}
          onRemoveAttachment={(id) => setAttachments((list) => list.filter((a) => a.document_id !== id))}
          onOpenAttachment={(a) => openSource({ documentId: a.document_id, title: a.filename, label: "Attached document", quotes: [] })}
          onUpload={(file) => void uploadDocument(file).then((att) => att && attach(att))}
          onPickDocuments={() => setPickerOpen(true)}
          onSend={(t) => void send(t)}
          onStop={() => abortRef.current?.abort()}
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
      <header className="relative z-20 flex items-center justify-between gap-3 bg-background/80 px-3 py-2 backdrop-blur-xs lg:px-4">
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
          <h1 className="ml-1 truncate font-display text-base font-normal text-ink" data-testid="chat-title">
            {active?.title?.trim() || (sessionId ? "Untitled conversation" : "New conversation")}
          </h1>
        </div>

        <div className="flex shrink-0 items-center gap-2">
          {sessionId && messages.length > 0 && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button
                  type="button"
                  title="Download this conversation"
                  aria-label="Download this conversation"
                  data-testid="chat-export"
                  className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs font-medium hover:bg-secondary"
                >
                  <Icon name="download" style={{ fontSize: 16 }} />
                  <span className="hidden md:inline">Download</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-48">
                <DropdownMenuItem
                  data-testid="chat-export-docx"
                  onSelect={() =>
                    void downloadFile(`/api/chat/sessions/${encodeURIComponent(sessionId)}/export.docx`, "conversation.docx").catch((err) =>
                      appToast(err instanceof Error ? err.message : "The download failed"),
                    )
                  }
                >
                  Word document (.docx)
                </DropdownMenuItem>
                <DropdownMenuItem
                  data-testid="chat-export-md"
                  onSelect={() => {
                    const title = active?.title?.trim() || "Conversation";
                    downloadText(safeFilename(title), conversationAsMarkdown(title, messages));
                  }}
                >
                  Markdown (.md)
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
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
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            <span>Sources</span>
            <span className="rounded bg-wine-soft px-1.5 py-0.5 font-mono text-xs font-semibold text-wine">
              {threadDocs.length}
            </span>
          </button>
        </div>
      </header>

      <div ref={splitRef} className="relative flex min-h-0 flex-1 overflow-hidden">
      <section className="relative flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden">

        {/* Chat Thread Messages Area */}
        <div ref={scrollRef} onScroll={onThreadScroll} className="flex-1 overflow-y-auto px-4 py-5 lg:px-6" data-testid="chat-thread">
          <div className={cn("mx-auto max-w-3xl", empty ? "flex min-h-full flex-col justify-center" : "space-y-7")}>
            {loadingThread && (
              <div className="flex items-center gap-2 text-sm text-muted-foreground py-10 justify-center">
                <Sparkles className="w-4 h-4 animate-spin text-primary" />
                <span>Loading conversation…</span>
              </div>
            )}

            {empty && (
              <EmptyThread
                composer={composerEl}
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
                          key={f.document_id ?? f.filename}
                          type="button"
                          onClick={() =>
                            f.document_id &&
                            openSource({ documentId: f.document_id, title: f.filename, label: "Attached document", quotes: [] })
                          }
                          className="inline-flex items-center gap-1 rounded-md border border-border bg-card px-2 py-0.5 text-xs text-foreground hover:bg-secondary"
                        >
                          <FileText className="h-3 w-3 text-muted-foreground" />
                          <span className="max-w-[220px] truncate">{f.filename}</span>
                        </button>
                      ))}
                    </div>
                  )}
                  {editingAt === i ? (
                    <div className="w-full max-w-[85%] space-y-2" data-testid="message-edit">
                      <textarea
                        autoFocus
                        value={editText}
                        onChange={(e) => setEditText(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing && editText.trim()) {
                            e.preventDefault();
                            resend(editText, m.files ?? []);
                          }
                          if (e.key === "Escape") setEditingAt(null);
                        }}
                        rows={3}
                        aria-label="Edit your message"
                        className="w-full resize-none rounded-2xl border border-border bg-card px-4 py-3 text-[15px] leading-relaxed focus:outline-none focus-visible:border-wine/50"
                      />
                      <div className="flex justify-end gap-2">
                        <button type="button" onClick={() => setEditingAt(null)} className="rounded-full border border-border px-3 py-1.5 text-xs font-medium hover:bg-secondary">
                          Cancel
                        </button>
                        <button
                          type="button"
                          disabled={!editText.trim()}
                          onClick={() => resend(editText, m.files ?? [])}
                          data-testid="message-edit-send"
                          className="rounded-full bg-primary px-3 py-1.5 text-xs font-semibold text-primary-foreground disabled:opacity-50"
                        >
                          Send
                        </button>
                      </div>
                    </div>
                  ) : (
                    <div className="max-w-[85%] whitespace-pre-wrap rounded-3xl bg-secondary px-4 py-2.5 text-[15.5px] leading-relaxed text-foreground">
                      {m.content}
                    </div>
                  )}
                  <div className="flex items-center gap-2 px-1 text-xs text-muted-foreground">
                    {m.created_at && (
                      <time dateTime={m.created_at}>
                        {new Date(m.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                      </time>
                    )}
                    {i === messages.length - 2 && !streaming && editingAt !== i && (
                      <button
                        type="button"
                        onClick={() => {
                          setEditText(m.content);
                          setEditingAt(i);
                        }}
                        data-testid="message-edit-open"
                        className="inline-flex items-center gap-1 rounded-md px-1.5 py-0.5 hover:bg-secondary hover:text-foreground"
                      >
                        <Icon name="edit" style={{ fontSize: 14 }} /> Edit
                      </button>
                    )}
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

        {showJump && (
          <button
            type="button"
            onClick={jumpToLatest}
            data-testid="chat-jump-latest"
            className="absolute bottom-32 left-1/2 z-10 inline-flex -translate-x-1/2 items-center gap-1 rounded-full border border-border bg-card px-3 py-1.5 text-xs font-medium text-foreground shadow-md hover:bg-secondary"
          >
            <Icon name="arrow_downward" style={{ fontSize: 14 }} /> Jump to latest
          </button>
        )}

        {!empty && composerEl}

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
            className="group relative hidden w-1.5 shrink-0 cursor-col-resize bg-border/70 transition-colors hover:bg-wine/40 focus-visible:bg-wine/50 focus-visible:outline-none lg:block"
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

      {matterPrompt && <MatterForUpload onChoose={matterPrompt.resolve} />}

      <DocumentPicker
        open={pickerOpen}
        onOpenChange={setPickerOpen}
        selected={attachments.map((a) => a.document_id)}
        onPick={(doc) => attach({ document_id: doc.document_id, filename: doc.title })}
      />
    </div>
  );
}
