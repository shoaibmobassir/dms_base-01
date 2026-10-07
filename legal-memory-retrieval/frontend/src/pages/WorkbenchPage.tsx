import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { Link, Navigate, useParams, useSearchParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { useMatter } from "@/api/resources";
import { archiveProject, useProject, useWorkspaceItems, type Level, type WorkspaceKind } from "@/api/workspaces";
import { useConfirm } from "@/components/common/Confirm";
import { EmptyState, Icon, MonoId } from "@/components/common/primitives";
import { EditorGroup } from "@/components/workbench/EditorGroup";
import { Explorer, type OpenRequest } from "@/components/workbench/Explorer";
import { ChangesView, QuickOpen, SearchView, StatusBar, WorkbenchCommands, type WorkbenchCommand } from "@/components/workbench/panels";
import { EditProjectDialog, ProjectMembersDialog } from "@/components/workbench/ProjectDialogs";
import { NewReviewDialog, ReviewsView } from "@/components/workbench/ReviewDialogs";
import { PlaybooksView } from "@/components/workbench/Playbooks";
import type { PlaybookSummary } from "@/api/playbooks";
import { AssistantView } from "@/components/workbench/AssistantView";
import { useWorkbench, type SideView } from "@/components/workbench/state";
import { useWorkspaceUpload } from "@/components/workbench/useWorkspaceUpload";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
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

function Workbench({ kind, id }: { kind: WorkspaceKind; id: string }) {
  const info = useWorkspaceInfo(kind, id);
  usePageTitle(info.label);
  const { state, dispatch, loaded } = useWorkbench(kind, id);
  const [searchParams, setSearchParams] = useSearchParams();
  const [quickOpen, setQuickOpen] = useState(false);
  const [commands, setCommands] = useState(false);
  const [people, setPeople] = useState(false);
  const [details, setDetails] = useState(false);
  const [seed, setSeed] = useState<{ text: string; nonce: number } | undefined>(undefined);
  const [reviewPlaybook, setReviewPlaybook] = useState<PlaybookSummary | null>(null);
  const project = useProject(id, kind === "project");
  const queryClient = useQueryClient();
  const confirm = useConfirm();
  const { toast } = useApp();
  const canEdit = info.level === "edit" || info.level === "manage";

  const open = useCallback(
    (r: OpenRequest) => {
      dispatch({ type: "open", tab: r.write ? { kind: "write", documentId: r.documentId, title: r.title }
        : { kind: "document", documentId: r.documentId, title: r.title, params: r.params }, toSide: r.toSide, preview: r.preview && !r.write });
    },
    [dispatch],
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
    if (review) dispatch({ type: "open", tab: { kind: "review", reviewId: review, title: "Review" } });
    if (doc || review) {
      const next = new URLSearchParams(searchParams);
      next.delete("doc");
      next.delete("review");
      setSearchParams(next, { replace: true });
    }
  }, [loaded, searchParams, setSearchParams, open, dispatch]);

  const focusedGroup = state.groups[state.focused];
  const activeTab = focusedGroup?.tabs.find((t) => t.id === focusedGroup.active) ?? null;
  const activeDocumentId = activeTab && activeTab.kind !== "review" ? activeTab.documentId : null;
  const openDocs = useMemo(() => {
    const seen = new Map<string, string>();
    for (const g of state.groups) for (const t of g.tabs) if (t.kind === "document" && !seen.has(t.documentId)) seen.set(t.documentId, t.title ?? "");
    return [...seen].map(([documentId, title]) => ({ documentId, title }));
  }, [state.groups]);
  const setSide = useCallback((side: SideView) => dispatch({ type: "side", side: state.side === side ? null : side }), [dispatch, state.side]);

  const archive = useCallback(async () => {
    if (!project.data) return;
    const archived = !!project.data.archived_at;
    if (!archived && !(await confirm({ title: "Archive this project?", description: "It becomes read-only and moves to Archived. Owners can restore it.", confirmLabel: "Archive project" }))) return;
    try {
      await archiveProject(id, !archived);
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(id) || q.queryKey.includes("projects") });
      toast(archived ? "Project restored" : "Project archived");
    } catch (err) {
      toast(firmError(err));
    }
  }, [project.data, id, confirm, queryClient, toast]);

  const commandList: WorkbenchCommand[] = useMemo(
    () => [
      { id: "quick-open", group: "Go", title: "Open a document by name", keys: "⌘P", run: () => setQuickOpen(true) },
      { id: "explorer", group: "View", title: "Show explorer", keys: "⇧⌘E", run: () => dispatch({ type: "side", side: "explorer" }) },
      { id: "search", group: "View", title: "Search this workspace", keys: "⇧⌘F", run: () => dispatch({ type: "side", side: "search" }) },
      { id: "changes", group: "View", title: "Show the document's changes and versions", keys: "⇧⌘H", run: () => dispatch({ type: "side", side: "changes" }) },
      { id: "assistant", group: "View", title: "Ask the Assistant about this workspace", keys: "⇧⌘A", run: () => dispatch({ type: "side", side: "assistant" }) },
      { id: "playbooks", group: "View", title: "Playbooks", run: () => dispatch({ type: "side", side: "playbooks" }) },
      { id: "reviews", group: "View", title: "Tabular reviews", run: () => dispatch({ type: "side", side: "reviews" }) },
      { id: "toggle-side", group: "View", title: "Show or hide the side bar", keys: "⌘B", run: () => dispatch({ type: "side", side: state.side ? null : "explorer" }) },
      { id: "split", group: "Editor", title: "Split editor", keys: "⌘\\", run: () => dispatch({ type: "split" }), when: !!activeTab },
      { id: "close-tab", group: "Editor", title: "Close tab", keys: "⌥W", run: () => activeTab && dispatch({ type: "close", group: state.focused, tabId: activeTab.id }), when: !!activeTab },
      { id: "close-all", group: "Editor", title: "Close all tabs", run: () => dispatch({ type: "closeAll" }) },
      { id: "move-tab", group: "Editor", title: "Move tab to the other group", run: () => activeTab && dispatch({ type: "moveToOtherGroup", group: state.focused, tabId: activeTab.id }), when: !!activeTab },
      { id: "edit-word", group: "Editor", title: "Edit this document in the Word editor", run: () => activeTab?.kind === "document" && open({ documentId: activeTab.documentId, title: activeTab.title ?? "", write: true }), when: activeTab?.kind === "document" },
      { id: "keep-open", group: "Editor", title: "Keep this tab open (not a preview)", run: () => activeTab && dispatch({ type: "pin", group: state.focused, tabId: activeTab.id }), when: !!activeTab?.preview },
      { id: "upload", group: "Workspace", title: "Upload files", run: () => uploader.pick(""), when: canEdit },
      { id: "people", group: "Workspace", title: "People in this project", run: () => setPeople(true), when: kind === "project" && !!project.data },
      { id: "details", group: "Workspace", title: "Project details", run: () => setDetails(true), when: kind === "project" && info.level === "manage" },
      { id: "archive", group: "Workspace", title: project.data?.archived_at ? "Restore project" : "Archive project", run: () => void archive(), when: kind === "project" && info.level === "manage" },
    ],
    [dispatch, state.side, state.focused, activeTab, uploader, canEdit, kind, project.data, info.level, archive, open],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const meta = e.metaKey || e.ctrlKey;
      const k = e.key.toLowerCase();
      if (meta && e.shiftKey && k === "p") {
        e.preventDefault();
        setCommands(true);
      } else if (meta && !e.shiftKey && k === "p") {
        e.preventDefault();
        setQuickOpen(true);
      } else if (meta && e.key === "\\") {
        e.preventDefault();
        dispatch({ type: "split" });
      } else if (meta && !e.shiftKey && k === "b") {
        e.preventDefault();
        dispatch({ type: "side", side: state.side ? null : "explorer" });
      } else if (meta && e.shiftKey && k === "f") {
        e.preventDefault();
        dispatch({ type: "side", side: "search" });
      } else if (meta && e.shiftKey && k === "a") {
        e.preventDefault();
        dispatch({ type: "side", side: "assistant" });
      } else if (meta && e.shiftKey && k === "h") {
        e.preventDefault();
        dispatch({ type: "side", side: "changes" });
      } else if (meta && e.shiftKey && k === "e") {
        e.preventDefault();
        dispatch({ type: "side", side: "explorer" });
      } else if (e.altKey && k === "w" && activeTab) {
        e.preventDefault();
        dispatch({ type: "close", group: state.focused, tabId: activeTab.id });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dispatch, state.side, state.focused, activeTab]);

  if (info.missing) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState icon="lock" title="Workspace not found" description="It does not exist, or you are not one of its people." action={<Button asChild variant="outline"><Link to="/projects">Your projects</Link></Button>} />
      </div>
    );
  }

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench">
      <header className="flex h-11 shrink-0 items-center gap-2 border-b border-border bg-paper px-3">
        <Icon name={kind === "matter" ? "gavel" : kind === "project" ? "folder_special" : kind === "firm" ? "library_books" : "person"} className="text-wine" style={{ fontSize: 20 }} />
        <h1 className="min-w-0 truncate font-display text-lg text-ink" data-testid="workbench-title">{info.label}</h1>
        {info.code && <MonoId>{info.code}</MonoId>}
        {project.data?.matter && (
          <Link to={`/matters/${encodeURIComponent(project.data.matter.matter_id)}`} className="hidden items-center gap-1 rounded-full bg-wine-soft px-2 py-0.5 text-xs text-wine hover:underline md:flex">
            <Icon name="gavel" style={{ fontSize: 13 }} /> {project.data.matter.matter_code}
          </Link>
        )}
        {project.data?.archived_at && <span className="rounded-full bg-warning-soft px-2 py-0.5 text-xs text-warning-ink">Archived · read only</span>}
        <div className="flex-1" />
        {kind === "project" && project.data && (
          <Button variant="ghost" size="sm" onClick={() => setPeople(true)} data-testid="workbench-people">
            <Icon name="group" style={{ fontSize: 16 }} /> {project.data.members.length}
          </Button>
        )}
        {kind === "matter" && (
          <Button variant="ghost" size="sm" asChild>
            <Link to={`/matters/${encodeURIComponent(id)}`}><Icon name="info" style={{ fontSize: 16 }} /> Matter page</Link>
          </Button>
        )}
        <Button variant="ghost" size="sm" onClick={() => setCommands(true)} title="Commands (⇧⌘P)" data-testid="workbench-commands-button">
          <Icon name="terminal" style={{ fontSize: 16 }} /> Commands
        </Button>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav className="flex w-11 shrink-0 flex-col items-center gap-1 border-r border-border bg-paper py-2" aria-label="Workbench views">
          <ActivityButton icon="folder_copy" label="Explorer (⇧⌘E)" active={state.side === "explorer"} onClick={() => setSide("explorer")} testId="activity-explorer" />
          <ActivityButton icon="search" label="Search (⇧⌘F)" active={state.side === "search"} onClick={() => setSide("search")} testId="activity-search" />
          {kind !== "firm" && <ActivityButton icon="edit_note" label="Assistant (⇧⌘A)" active={state.side === "assistant"}
            onClick={() => { setSide("assistant"); if (state.sideWidth < 360) dispatch({ type: "sideWidth", width: 400 }); }} testId="activity-assistant" />}
          <ActivityButton icon="table_chart" label="Tabular reviews" active={state.side === "reviews"} onClick={() => setSide("reviews")} testId="activity-reviews" />
          <ActivityButton icon="menu_book" label="Playbooks" active={state.side === "playbooks"} onClick={() => setSide("playbooks")} testId="activity-playbooks" />
          <ActivityButton icon="history" label="Changes (⇧⌘H)" active={state.side === "changes"} onClick={() => setSide("changes")} testId="activity-changes" />
        </nav>
        {state.side && (
          <SidePanel width={state.sideWidth} onResize={(w) => dispatch({ type: "sideWidth", width: w })}>
            {state.side === "explorer" && (
              <Explorer
                kind={kind}
                id={id}
                label={info.label}
                canEdit={canEdit && !project.data?.archived_at}
                activeDocumentId={activeDocumentId}
                onOpen={open}
                onUpload={(folder, files) => (files ? void uploader.upload(files, folder) : uploader.pick(folder))}
                onFill={kind === "firm" ? undefined : (d) => {
                  setSeed({
                    text: `Fill in the blanks of “${d.title}” (the open document): replace each placeholder in [square brackets], and any ` +
                      `blank such as “____”, with the right details. Ask me first for anything you need, then propose the edits.`,
                    nonce: Date.now(),
                  });
                  dispatch({ type: "side", side: "assistant" });
                  if (state.sideWidth < 360) dispatch({ type: "sideWidth", width: 400 });
                }}
              />
            )}
            {state.side === "search" && <SearchView kind={kind} id={id} onOpen={open} />}
            {state.side === "assistant" && kind !== "firm" && (
              <AssistantView kind={kind} id={id} label={info.label} openDocs={openDocs} onOpen={open} seed={seed} />
            )}
            {state.side === "playbooks" && (
              <PlaybooksView
                onUse={(p) => {
                  setSeed({ text: `Follow the playbook “${p.title}” (${p.playbook_id}). `, nonce: Date.now() });
                  dispatch({ type: "side", side: "assistant" });
                  if (state.sideWidth < 360) dispatch({ type: "sideWidth", width: 400 });
                }}
                onStartReview={(p) => setReviewPlaybook(p)}
              />
            )}
            {state.side === "reviews" && (
              <ReviewsView kind={kind} id={id} canEdit={canEdit && !project.data?.archived_at}
                onOpen={(reviewId, title) => dispatch({ type: "open", tab: { kind: "review", reviewId, title } })} />
            )}
            {state.side === "changes" && (
              <ChangesView
                kind={kind}
                id={id}
                documentId={activeDocumentId}
                title={activeTab?.title}
                onOpenVersion={(versionId) => {
                  if (!activeTab) return;
                  const p = new URLSearchParams(activeTab.params ?? "");
                  p.set("version", versionId);
                  p.delete("page");
                  dispatch({ type: "params", group: state.focused, tabId: activeTab.id, params: p.toString() });
                }}
              />
            )}
          </SidePanel>
        )}
        <div className="flex min-w-0 flex-1">
          {state.groups.map((g, i) => (
            <div key={i} className={cn("flex min-w-0 flex-1", i > 0 && "border-l border-border")}>
              <EditorGroup group={g} index={i} state={state} dispatch={dispatch} onOpen={open} />
            </div>
          ))}
        </div>
      </div>

      <StatusBar documentId={activeDocumentId} workspaceLabel={info.label} level={info.level} />
      {uploader.busy && (
        <div className="pointer-events-none fixed bottom-10 right-6 rounded-md bg-ink px-3 py-2 text-xs text-paper shadow-lg">Uploading…</div>
      )}
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

function SidePanel({ width, onResize, children }: { width: number; onResize: (w: number) => void; children: ReactNode }) {
  const start = (e: ReactPointerEvent) => {
    const x0 = e.clientX;
    const w0 = width;
    const move = (ev: PointerEvent) => onResize(w0 + ev.clientX - x0);
    const up = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
    };
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  };
  return (
    <aside className="relative hidden shrink-0 border-r border-border bg-paper/60 md:block" style={{ width }}>
      {children}
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize side bar"
        onPointerDown={start}
        className="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize hover:bg-wine/20"
      />
    </aside>
  );
}
