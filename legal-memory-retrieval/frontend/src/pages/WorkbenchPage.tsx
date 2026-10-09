import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent as ReactKeyboardEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { useMatter } from "@/api/resources";
import { archiveProject, deleteProject, useProject, useWorkspaceItems, type Level, type WorkspaceKind } from "@/api/workspaces";
import { useConfirm } from "@/components/common/Confirm";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";
import { EmptyState, Icon, MonoId } from "@/components/common/primitives";
import { EditorGroup } from "@/components/workbench/EditorGroup";
import { Explorer, type OpenRequest } from "@/components/workbench/Explorer";
import { ChangesView, QuickOpen, SearchView, StatusBar, WorkbenchCommands, type WorkbenchCommand } from "@/components/workbench/panels";
import { EditProjectDialog, ProjectMembersDialog } from "@/components/workbench/ProjectDialogs";
import { NewReviewDialog, ReviewsView } from "@/components/workbench/ReviewDialogs";
import { PlaybooksView } from "@/components/workbench/Playbooks";
import type { PlaybookSummary } from "@/api/playbooks";
import { AssistantView } from "@/components/workbench/AssistantView";
import { registerAssistantRequests } from "@/lib/assistantRequest";
import { EMPTY, useGuardedClose, useWorkbench, type SideView } from "@/components/workbench/state";
import { useWorkspaceUpload, type UploadProgress } from "@/components/workbench/useWorkspaceUpload";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { keys, typingTarget } from "@/lib/keys";
import { useMediaQuery } from "@/lib/use-media-query";
import { usePageTitle } from "@/lib/use-page-title";
import { cn } from "@/lib/utils";

const KINDS: WorkspaceKind[] = ["matter", "project", "library", "firm"];

/**
 * The workbench (plan 22, W1): a matter, a project or your library opened as one workspace — its folders and
 * documents on the left, several documents as tabs, two side by side, everything reachable from the keyboard.
 */
export function WorkbenchPage() {
  const { kind = "", id = "" } = useParams();
  if (!KINDS.includes(kind as WorkspaceKind)) return <Navigate to="/projects" replace />;
  return <Workbench key={`${kind}:${id}`} kind={kind as WorkspaceKind} id={id} />;
}

type Info = { label: string; code?: string; level?: Level; ready: boolean; missing: boolean };

function useWorkspaceInfo(kind: WorkspaceKind, id: string): Info {
  const matter = useMatter(kind === "matter" ? id : "");
  const project = useProject(id, kind === "project");
  const firmRoot = useWorkspaceItems("firm", "templates", { enabled: kind === "firm" });
  if (kind === "matter") {
    const m = matter.data;
    const lvl = m?.my_level;
    return { label: m?.matter.title ?? id, code: m?.matter.matter_code, level: lvl && lvl !== "none" ? lvl : undefined, ready: !!m || matter.isError, missing: matter.isError };
  }
  if (kind === "project") {
    const p = project.data;
    return { label: p?.title ?? "Project", level: p?.my_level, ready: !!p || project.isError, missing: project.isError };
  }
  if (kind === "firm") {
    const lvl = firmRoot.data?.my_level;
    return { label: "Firm templates", level: lvl, ready: !!firmRoot.data, missing: firmRoot.isError };
  }
  return { label: "My library", level: "manage", ready: true, missing: false };
}

/** Does a keydown match a shortcut written the Mac way ("⇧⌘P", "⌥W", "⌘\\")? ⌘ means Ctrl off a Mac. */
function matches(e: KeyboardEvent, shortcut: string): boolean {
  const meta = shortcut.includes("⌘");
  const shift = shortcut.includes("⇧");
  const alt = shortcut.includes("⌥");
  const key = shortcut.replace(/[⌘⇧⌥⌃]/g, "");
  if ((e.metaKey || e.ctrlKey) !== meta || e.shiftKey !== shift || e.altKey !== alt) return false;
  // e.code, not e.key: ⌥W types "∑" on a Mac, but the key is still W.
  const code = key === "\\" ? "Backslash" : `Key${key.toUpperCase()}`;
  return e.code === code;
}

function Workbench({ kind, id }: { kind: WorkspaceKind; id: string }) {
  const info = useWorkspaceInfo(kind, id);
  usePageTitle(info.label);
  const { state, dispatch, loaded } = useWorkbench(kind, id);
  const [searchParams, setSearchParams] = useSearchParams();
  const [quickOpen, setQuickOpen] = useState(false);
  const [commands, setCommands] = useState(false);
  const [people, setPeople] = useState(false);
  const [details, setDetails] = useState(false);
  const [seed, setSeed] = useState<{ text: string; nonce: number; send?: boolean } | undefined>(undefined);
  const wide = useMediaQuery("(min-width: 768px)");
  const openAssistant = useCallback(() => dispatch({ type: "assistant", open: true }), [dispatch]);
  // A question raised inside an open document (e.g. "compare with precedent") is asked in the Assistant panel.
  useEffect(() => {
    if (kind === "firm") return undefined;
    return registerAssistantRequests((r) => {
      setSeed({ text: r.prompt, nonce: Date.now(), send: true });
      openAssistant();
    });
  }, [kind, openAssistant]);
  const [reviewPlaybook, setReviewPlaybook] = useState<PlaybookSummary | null>(null);
  const project = useProject(id, kind === "project");
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const { toast } = useApp();
  const archived = !!project.data?.archived_at;
  // One answer to "can I change things here?" for every control: edit rights and, for a project, not archived.
  const writable = (info.level === "edit" || info.level === "manage") && !archived;
  const close = useGuardedClose(state, dispatch, confirm);

  const open = useCallback(
    (r: OpenRequest) => {
      dispatch({ type: "open", tab: r.write ? { kind: "write", documentId: r.documentId, title: r.title }
        : { kind: "document", documentId: r.documentId, title: r.title, params: r.params }, toSide: r.toSide, preview: r.preview && !r.write });
      // On a phone the list covers the document: opening one shows it.
      if (!wide) dispatch({ type: "side", side: null });
    },
    [dispatch, wide],
  );
  const uploader = useWorkspaceUpload(kind, id, (ids) => {
    if (ids.length === 1) open({ documentId: ids[0], title: "" });
  });

  // ?doc=DOC-… (from a document page or a link) opens that document once the saved layout is in.
  const handled = useRef(false);
  useEffect(() => {
    if (!loaded || handled.current) return;
    handled.current = true;
    const doc = searchParams.get("doc");
    const review = searchParams.get("review");
    if (doc) open({ documentId: doc, title: "" });
    if (review) {
      dispatch({ type: "open", tab: { kind: "review", reviewId: review, title: "Review" } });
      const next = new URLSearchParams(searchParams);
      next.delete("review");
      setSearchParams(next, { replace: true });
    }
  }, [loaded, searchParams, setSearchParams, open, dispatch]);

  const focusedGroup = state.groups[state.focused];
  const activeTab = focusedGroup?.tabs.find((t) => t.id === focusedGroup.active) ?? null;
  const activeDocumentId = activeTab && activeTab.kind !== "review" ? activeTab.documentId : null;

  // The address bar names the open document, so a copied link (or a reload) comes back to it.
  useEffect(() => {
    if (!loaded || !handled.current) return;
    const current = searchParams.get("doc");
    if ((activeDocumentId ?? null) === current) return;
    const next = new URLSearchParams(searchParams);
    if (activeDocumentId) next.set("doc", activeDocumentId);
    else next.delete("doc");
    setSearchParams(next, { replace: true });
  }, [activeDocumentId, loaded, searchParams, setSearchParams]);

  const openDocs = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of state.groups) for (const t of g.tabs) if (t.kind === "document" && !seen.has(t.documentId)) seen.set(t.documentId, t.title ?? "");
    return [...seen].map(([documentId, title]) => ({ documentId, title }));
  }, [state.groups]);
  const setSide = useCallback((side: SideView) => dispatch({ type: "side", side: state.side === side ? null : side }), [dispatch, state.side]);

  const archive = useCallback(async () => {
    if (!project.data) return;
    if (!archived && !(await confirm({ title: "Archive this project?", description: "It becomes read-only and moves to Archived. Owners can restore it.", confirmLabel: "Archive project" }))) return;
    try {
      await archiveProject(id, !archived);
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(id) || q.queryKey.includes("projects") });
      toast(archived ? "Project restored" : "Project archived");
    } catch (err) {
      toast(firmError(err));
    }
  }, [project.data, archived, id, confirm, queryClient, toast]);

  const [deleted, setDeleted] = useState(false);
  const remove = useCallback(async () => {
    if (!project.data) return;
    const ok = await confirm({
      title: `Delete “${project.data.title}”?`,
      description: "Only an empty project can be deleted: move, file or remove its documents and reviews first. This cannot be undone.",
      confirmLabel: "Delete project",
      destructive: true,
    });
    if (!ok) return;
    try {
      await deleteProject(id);
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("projects") });
      toast("Project deleted");
      setDeleted(true);
    } catch (err) {
      toast(firmError(err));
    }
  }, [project.data, id, confirm, queryClient, toast]);

  const commandList: WorkbenchCommand[] = useMemo(
    () => [
      { id: "quick-open", group: "Go", title: "Open a document by name", keys: "⌘P", run: () => setQuickOpen(true) },
      { id: "commands", group: "Go", title: "Show all commands", keys: "⇧⌘P", run: () => setCommands(true), hidden: true },
      { id: "explorer", group: "View", title: "Show files", keys: "⇧⌘E", run: () => dispatch({ type: "side", side: "explorer" }) },
      { id: "search", group: "View", title: "Search this workspace", keys: "⇧⌘F", run: () => dispatch({ type: "side", side: "search" }) },
      { id: "changes", group: "View", title: "Show the document's versions", keys: "⌥⌘Y", run: () => dispatch({ type: "side", side: "changes" }) },
      { id: "assistant", group: "View", title: state.assistant ? "Hide the Assistant" : "Ask the Assistant about this workspace", keys: "⌥⌘A",
        run: () => dispatch({ type: "assistant", open: !state.assistant }), when: kind !== "firm" },
      { id: "playbooks", group: "View", title: "Playbooks", run: () => dispatch({ type: "side", side: "playbooks" }) },
      { id: "reviews", group: "View", title: "Tabular reviews", run: () => dispatch({ type: "side", side: "reviews" }), when: kind !== "firm" },
      { id: "toggle-side", group: "View", title: "Show or hide the side bar", keys: "⌘B", run: () => dispatch({ type: "side", side: state.side ? null : "explorer" }) },
      { id: "reset-layout", group: "View", title: "Reset this workspace's layout (close every tab)", run: () => dispatch({ type: "load", state: EMPTY }) },
      { id: "split", group: "Editor", title: "Split editor", keys: "⌘\\", run: () => dispatch({ type: "split" }), when: !!activeTab },
      { id: "close-tab", group: "Editor", title: "Close tab", keys: "⌥W", run: () => activeTab && void close({ type: "close", group: state.focused, tabId: activeTab.id }), when: !!activeTab },
      { id: "close-all", group: "Editor", title: "Close all tabs", run: () => void close({ type: "closeAll" }) },
      { id: "move-tab", group: "Editor", title: "Move tab to the other group", run: () => activeTab && dispatch({ type: "moveToOtherGroup", group: state.focused, tabId: activeTab.id }), when: !!activeTab },
      { id: "edit-word", group: "Editor", title: "Edit this document in the Word editor", run: () => activeTab?.kind === "document" && open({ documentId: activeTab.documentId, title: activeTab.title ?? "", write: true }), when: activeTab?.kind === "document" },
      { id: "keep-open", group: "Editor", title: "Keep this tab open (not a preview)", run: () => activeTab && dispatch({ type: "pin", group: state.focused, tabId: activeTab.id }), when: !!activeTab?.preview },
      { id: "upload", group: "Workspace", title: "Upload files", run: () => uploader.pick(""), when: writable },
      { id: "people", group: "Workspace", title: "People in this project", run: () => setPeople(true), when: kind === "project" && !!project.data },
      { id: "details", group: "Workspace", title: "Project details", run: () => setDetails(true), when: kind === "project" && info.level === "manage" },
      { id: "archive", group: "Workspace", title: archived ? "Restore project" : "Archive project", run: () => void archive(), when: kind === "project" && info.level === "manage" },
      { id: "delete", group: "Workspace", title: "Delete project", run: () => void remove(), when: kind === "project" && info.level === "manage" },
    ],
    [dispatch, state.side, state.assistant, state.focused, activeTab, uploader, writable, kind, project.data, info.level, archived, archive, remove, open, close],
  );

  // One shortcut map: the command list. Shortcuts that would steal keys from typing (⌘B is bold in an editor) wait
  // until focus is out of the text; the palettes work everywhere.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.defaultPrevented || e.isComposing) return;
      const hit = commandList.find((c) => c.keys && c.when !== false && matches(e, c.keys));
      if (!hit) return;
      if (typingTarget(e) && hit.id !== "quick-open" && hit.id !== "commands") return;
      e.preventDefault();
      hit.run();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [commandList]);

  if (deleted) return <Navigate to="/projects" replace />;
  if (info.missing) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState icon="lock" title="Workspace not found" description="It does not exist, or you are not one of its people." action={<Button asChild variant="outline"><Link to="/projects">Your projects</Link></Button>} />
      </div>
    );
  }

  const sideTitle: Record<SideView, string> = { explorer: "Files", search: "Search", changes: "Versions", reviews: "Tabular reviews", playbooks: "Playbooks" };
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-paper px-3">
        <Icon name={kind === "matter" ? "gavel" : kind === "project" ? "folder_special" : kind === "firm" ? "library_books" : "person_book"} className="shrink-0 text-wine" style={{ fontSize: 20 }} />
        <h1 className="min-w-0 truncate font-display text-lg text-ink" data-testid="workbench-title">{info.label}</h1>
        {info.code && <MonoId className="hidden sm:inline">{info.code}</MonoId>}
        {project.data?.matter && (
          <Link to={`/matters/${encodeURIComponent(project.data.matter.matter_id)}`} title={project.data.matter.matter_code}
            className="hidden min-w-0 items-center gap-1 rounded-full bg-wine-soft px-2 py-0.5 text-xs text-wine hover:underline md:flex">
            <Icon name="gavel" className="shrink-0" style={{ fontSize: 13 }} /> <span className="truncate">{project.data.matter.title}</span>
          </Link>
        )}
        {archived && <span className="shrink-0 rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning-ink">Archived · read only</span>}
        {kind === "library" && <span className="hidden shrink-0 text-xs text-muted-foreground lg:inline">Only you, and people you share a file with, can see these</span>}
        <div className="flex-1" />
        {kind === "project" && project.data && (
          <Button variant="ghost" size="sm" onClick={() => setPeople(true)} data-testid="workbench-people">
            <Icon name="group" style={{ fontSize: 16 }} /> <span className="hidden sm:inline">People</span> ({project.data.members.length})
          </Button>
        )}
        {kind === "matter" && (
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/matters/${encodeURIComponent(id)}`}><Icon name="info" style={{ fontSize: 16 }} /> <span className="hidden sm:inline">Matter page</span></Link>
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setCommands(true)} title={`Commands (${keys("⇧⌘P")})`} data-testid="workbench-commands-button">
          <Icon name="terminal" style={{ fontSize: 16 }} /> <span className="hidden sm:inline">Commands</span>
        </Button>
      </header>

      <div className="relative flex min-h-0 flex-1">
        <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-border bg-paper py-2" aria-label="Workbench views">
          <ActivityButton icon="folder_copy" label={`Files (${keys("⇧⌘E")})`} active={state.side === "explorer"} onClick={() => setSide("explorer")} testId="activity-explorer" />
          <ActivityButton icon="search" label={`Search (${keys("⇧⌘F")})`} active={state.side === "search"} onClick={() => setSide("search")} testId="activity-search" />
          {kind !== "firm" && (
            <ActivityButton icon="table_chart" label="Tabular reviews" active={state.side === "reviews"} onClick={() => setSide("reviews")} testId="activity-reviews" />
          )}
          <ActivityButton icon="menu_book" label="Playbooks" active={state.side === "playbooks"} onClick={() => setSide("playbooks")} testId="activity-playbooks" />
          <ActivityButton icon="history" label={`Versions (${keys("⌥⌘Y")})`} active={state.side === "changes"} onClick={() => setSide("changes")} testId="activity-changes" />
          {kind !== "firm" && (
            <>
              <div className="my-1 h-px w-6 bg-border" />
              <ActivityButton icon="edit_note" label={`Assistant (${keys("⌥⌘A")})`} active={state.assistant}
                onClick={() => dispatch({ type: "assistant", open: !state.assistant })} testId="activity-assistant" />
            </>
          )}
        </nav>
        {state.side && (
          <SidePanel side="left" title={sideTitle[state.side]} width={state.sideWidth} wide={wide} onClose={() => dispatch({ type: "side", side: null })}
            onResize={(w) => dispatch({ type: "sideWidth", width: w })}>
            <ErrorBoundary what={sideTitle[state.side]} resetKey={state.side}>
            {state.side === "explorer" && (
              <Explorer
                kind={kind}
                id={id}
                label={info.label}
                canEdit={writable}
                canManage={info.level === "manage" && !archived}
                activeDocumentId={activeDocumentId}
                onOpen={open}
                onUpload={(folder, files) => (files ? void uploader.upload(files, folder) : uploader.pick(folder))}
                onFill={kind === "firm" ? undefined : (d) => {
                  setSeed({
                    text: `Fill in the blanks of “${d.title}” (the open document): replace each placeholder in [square brackets], and any ` +
                      `blank such as “____”, with the right details. Ask me first for anything you need, then propose the edits.`,
                    nonce: Date.now(),
                  });
                  openAssistant();
                }}
              />
            )}
            {state.side === "search" && <SearchView kind={kind} id={id} onOpen={open} />}
            {state.side === "playbooks" && (
              <PlaybooksView
                onUse={(p) => {
                  setSeed({ text: `Follow the playbook “${p.title}” (${p.playbook_id}). `, nonce: Date.now() });
                  openAssistant();
                }}
                onStartReview={(p) => setReviewPlaybook(p)}
              />
            )}
            {state.side === "reviews" && (
              <ReviewsView kind={kind} id={id} canEdit={writable}
                onOpen={(reviewId, title) => dispatch({ type: "open", tab: { kind: "review", reviewId, title } })} />
            )}
            {state.side === "changes" && (
              <ChangesView
                kind={kind}
                id={id}
                documentId={activeDocumentId}
                title={activeTab?.title}
                canEdit={writable}
                onOpenVersion={(versionId) => {
                  if (!activeTab) return;
                  const p = new URLSearchParams(activeTab.params ?? "");
                  p.set("version", versionId);
                  p.delete("page");
                  dispatch({ type: "params", group: state.focused, tabId: activeTab.id, params: p.toString() });
                }}
              />
            )}
            </ErrorBoundary>
          </SidePanel>
        )}
        <div className="flex min-w-0 flex-1">
          {state.groups.map((g, i) => (
            <div key={i} className={cn("flex min-w-0 flex-1", i > 0 && "border-l border-border", i > 0 && !wide && "hidden")}>
              <EditorGroup group={g} index={i} state={state} dispatch={dispatch} onClose={(a) => void close(a)} onOpen={open} />
            </div>
          ))}
        </div>
        {state.assistant && kind !== "firm" && (
          <SidePanel side="right" title="Assistant" width={state.assistantWidth} wide={wide} onClose={() => dispatch({ type: "assistant", open: false })}
            onResize={(w) => dispatch({ type: "assistantWidth", width: w })}>
            <ErrorBoundary what="The Assistant">
              <AssistantView kind={kind} id={id} label={info.label} openDocs={openDocs} onOpen={open} seed={seed} />
            </ErrorBoundary>
          </SidePanel>
        )}
      </div>

      <StatusBar documentId={activeDocumentId} workspaceLabel={info.label} level={info.level} kind={kind} />
      <UploadToast progress={uploader.progress} />
      {uploader.element}
      <NewReviewDialog kind={kind} id={id} open={!!reviewPlaybook} onOpenChange={(o) => !o && setReviewPlaybook(null)}
        playbook={reviewPlaybook} onCreated={(r) => { setReviewPlaybook(null); dispatch({ type: "open", tab: { kind: "review", reviewId: r.review_id, title: r.title } }); }} />
      <QuickOpen kind={kind} id={id} open={quickOpen} onOpenChange={setQuickOpen} onOpen={open} />
      <WorkbenchCommands open={commands} onOpenChange={setCommands} commands={commandList} />
      {project.data && <ProjectMembersDialog project={project.data} open={people} onOpenChange={setPeople} />}
      {project.data && details && <EditProjectDialog project={project.data} open={details} onOpenChange={setDetails} />}
    </div>
  );
}

/** A quiet progress line while files are checked and uploaded. */
export function UploadToast({ progress }: { progress: UploadProgress }) {
  if (!progress) return null;
  const { phase, done, total } = progress;
  return (
    <div className="pointer-events-none fixed bottom-10 right-6 z-40 min-w-[220px] rounded-md bg-ink px-3 py-2 text-xs text-paper shadow-lg" role="status" data-testid="upload-progress">
      <div>{phase === "checking" ? `Checking ${total} ${total === 1 ? "file" : "files"}…` : `Uploading ${Math.min(done, total)} of ${total}…`}</div>
      <div className="mt-1.5 h-1 overflow-hidden rounded bg-paper/20">
        <div className="h-full bg-paper transition-[width]" style={{ width: `${total ? Math.max(5, (done / total) * 100) : 5}%` }} />
      </div>
    </div>
  );
}

function ActivityButton({ icon, label, active, onClick, testId }: { icon: string; label: string; active: boolean; onClick: () => void; testId: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      aria-pressed={active}
      title={label}
      onClick={onClick}
      className={cn(
        "relative flex h-9 w-9 items-center justify-center rounded-md transition-colors",
        active ? "text-wine" : "text-muted-foreground hover:bg-secondary hover:text-foreground",
      )}
      data-testid={testId}
    >
      {active && <span className="absolute -left-1 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-full bg-wine" />}
      <Icon name={icon} style={{ fontSize: 21 }} />
    </button>
  );
}

/**
 * A resizable panel beside the editors (left: files, search …; right: the Assistant). On a phone it covers the
 * editor instead, with a close button, so files are always reachable.
 */
function SidePanel({ side, title, width, wide, onResize, onClose, children }: {
  side: "left" | "right"; title: string; width: number; wide: boolean; onResize: (w: number) => void; onClose: () => void; children: ReactNode;
}) {
  const sign = side === "left" ? 1 : -1;
  const start = (e: ReactPointerEvent) => {
    const x0 = e.clientX;
    const w0 = width;
    const move = (ev: PointerEvent) => onResize(w0 + sign * (ev.clientX - x0));
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  const onKey = (e: ReactKeyboardEvent) => {
    const step = e.shiftKey ? 64 : 16;
    if (e.key === "ArrowLeft") onResize(width - sign * step);
    else if (e.key === "ArrowRight") onResize(width + sign * step);
    else return;
    e.preventDefault();
  };
  if (!wide) {
    return (
      <aside className={cn("absolute inset-y-0 z-20 flex flex-col bg-paper", side === "left" ? "left-11 right-0" : "inset-x-0")} aria-label={title} data-testid={`side-panel-${side}`}>
        <div className="flex h-9 shrink-0 items-center justify-between border-b border-border px-3 text-sm font-medium">
          {title}
          <button type="button" onClick={onClose} aria-label={`Close ${title}`} className="rounded p-1 text-muted-foreground hover:bg-secondary">
            <Icon name="close" style={{ fontSize: 18 }} />
          </button>
        </div>
        <div className="min-h-0 flex-1">{children}</div>
      </aside>
    );
  }
  return (
    <aside className={cn("relative shrink-0 bg-paper/60", side === "left" ? "border-r border-border" : "border-l border-border")} style={{ width }}
      aria-label={title} data-testid={`side-panel-${side}`}>
      {children}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label={`Resize ${title.toLowerCase()}`}
        aria-valuenow={width}
        tabIndex={0}
        onPointerDown={start}
        onKeyDown={onKey}
        className={cn("absolute inset-y-0 z-10 w-2 cursor-col-resize hover:bg-wine/20 focus-visible:bg-wine/30 focus-visible:outline-none", side === "left" ? "-right-1" : "-left-1")}
      />
    </aside>
  );
}
