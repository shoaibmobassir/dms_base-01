import { useCallback, useEffect, useState, type DragEvent, type KeyboardEvent as ReactKeyboardEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { archiveDocument, firmError } from "@/api/firm";
import { downloadDocument } from "@/api/resources";
import { ACCEPTED_HINT } from "@/api/uploads";
import {
  addTag,
  copyDocument,
  createFolder,
  deleteFolder,
  displayTitle,
  linkDocument,
  moveHome,
  placeInFolder,
  renameDocument,
  renameFolder,
  unlinkDocument,
  useSharedWithMe,
  useTagSuggestions,
  useWorkspaceItems,
  type WorkspaceDocument,
  type WorkspaceFolder,
  type WorkspaceItem,
  type WorkspaceKind,
} from "@/api/workspaces";
import { useConfirm } from "@/components/common/Confirm";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";
import { useWorkspaceUpload } from "./useWorkspaceUpload";
import { FolderPicker } from "./FolderPicker";
import { LibraryShareDialog, NewFromTemplateDialog, PromptDialog, TagsDialog, TargetDialog, type TargetChoice } from "./dialogs";

export type OpenRequest = { documentId: string; title: string; preview?: boolean; toSide?: boolean; params?: string; write?: boolean };

type Sort = "name" | "modified" | "type";

type Ctx = {
  kind: WorkspaceKind;
  id: string;
  label: string;
  canEdit: boolean;
  /** Archiving a document needs manage rights where it lives. */
  canManage: boolean;
  /** May add documents to the firm's templates (km.publish). */
  canCurate: boolean;
  copyToTemplates: (doc: WorkspaceDocument) => void;
  activeDocumentId: string | null;
  sort: Sort;
  selected: Set<string>;
  toggleSelected: (doc: WorkspaceDocument, range: boolean) => void;
  onOpen: (r: OpenRequest) => void;
  onUpload: (folder: string, files?: File[]) => void;
  ask: (a: Ask) => void;
  removeFolder: (path: string) => void;
  unlink: (doc: WorkspaceDocument) => void;
  archive: (docs: WorkspaceDocument[]) => void;
  /** A document dragged onto a folder (or the top level): file it there, or — from another workspace — add it there. */
  moveDoc: (source: DragSource, folder: string) => void;
};

const DOC_DRAG = "application/x-precentis-explorer-doc";
type DragSource = { documentId: string; title: string; kind: WorkspaceKind; id: string };

type Ask =
  | { type: "new-folder"; parent: string }
  | { type: "rename-folder"; path: string }
  | { type: "move"; docs: WorkspaceDocument[] }
  | { type: "link" | "copy" | "file"; doc: WorkspaceDocument }
  | { type: "link-many"; docs: WorkspaceDocument[] }
  | { type: "tags"; doc: WorkspaceDocument }
  | { type: "tag-many"; docs: WorkspaceDocument[] }
  | { type: "rename"; doc: WorkspaceDocument }
  | { type: "share"; doc: WorkspaceDocument };

export function iconFor(doc: { mime_type?: string | null; title?: string }): string {
  const t = (doc.mime_type ?? "") + (doc.title ?? "").toLowerCase();
  if (t.includes("pdf")) return "picture_as_pdf";
  if (t.includes("word") || t.includes(".docx")) return "article";
  if (t.includes("sheet") || t.includes(".xlsx") || t.includes(".csv")) return "table_chart";
  return "description";
}

/** A remembered per-person view setting (sort, hidden sections). Storage may be unavailable: then it lasts the visit. */
function useStored<T extends string>(key: string, initial: T): [T, (v: T) => void] {
  const [value, setValue] = useState<T>(() => {
    try {
      return (localStorage.getItem(key) as T | null) ?? initial;
    } catch {
      return initial;
    }
  });
  const set = useCallback((v: T) => {
    setValue(v);
    try {
      localStorage.setItem(key, v);
    } catch {
      // storage unavailable — keep it for this visit only
    }
  }, [key]);
  return [value, set];
}

function sorted(docs: WorkspaceItem[], sort: Sort): WorkspaceItem[] {
  if (sort === "name") return docs;
  const key = (d: WorkspaceItem) => (d.restricted ? "" : sort === "modified" ? d.updated_at ?? "" : `${iconFor(d)} ${d.title.toLowerCase()}`);
  return [...docs].sort((a, b) => (sort === "modified" ? key(b).localeCompare(key(a)) : key(a).localeCompare(key(b))));
}

/**
 * The explorer: the workspace being worked in, then — as collapsible sections — the person's library and the firm's
 * templates, so documents can be opened, filed and dragged between workspaces without leaving the workbench.
 */
export function Explorer(props: {
  kind: WorkspaceKind;
  id: string;
  label: string;
  canEdit: boolean;
  canManage?: boolean;
  activeDocumentId: string | null;
  onOpen: (r: OpenRequest) => void;
  onUpload: (folder: string, files?: File[]) => void;
  /** A document just made from a template: hand it to the Assistant to fill in. */
  onFill?: (doc: { document_id: string; title: string }) => void;
}) {
  const [sections, setSections] = useStored<"shown" | "hidden">("precentis.explorer.sections", "shown");
  const others = ([
    ["library", "me", "My library"],
    ["firm", "templates", "Firm templates"],
  ] as const).filter(([k]) => k !== props.kind);
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-explorer">
      <ExplorerRoot {...props} sectionsShown={sections === "shown"} onToggleSections={() => setSections(sections === "shown" ? "hidden" : "shown")} />
      {sections === "shown" && (
        <div className="max-h-[45%] shrink-0 overflow-y-auto border-t border-border" data-testid="explorer-sections">
          {others.map(([k, i, l]) => (
            <SectionRoot key={k} kind={k} id={i} label={l} activeDocumentId={props.activeDocumentId} onOpen={props.onOpen} />
          ))}
        </div>
      )}
    </div>
  );
}

/** A secondary root (library, templates): collapsed until opened, with its own uploads. */
function SectionRoot({ kind, id, label, activeDocumentId, onOpen }: {
  kind: WorkspaceKind; id: string; label: string; activeDocumentId: string | null; onOpen: (r: OpenRequest) => void;
}) {
  const root = useWorkspaceItems(kind, id, { folder: "" });
  const uploader = useWorkspaceUpload(kind, id, undefined, `workspace-upload-input-${kind}`);
  const canEdit = root.data ? root.data.my_level !== "read" : false;
  return (
    <>
      <ExplorerRoot kind={kind} id={id} label={label} canEdit={canEdit} canManage={root.data?.my_level === "manage"} activeDocumentId={activeDocumentId} onOpen={onOpen}
        onUpload={(folder, files) => (files ? void uploader.upload(files, folder) : uploader.pick(folder))} section />
      {uploader.element}
    </>
  );
}

/** One workspace's folders and documents (home and linked), with the actions a workbench needs. */
function ExplorerRoot({
  kind,
  id,
  label,
  canEdit,
  canManage = false,
  activeDocumentId,
  onOpen,
  onUpload,
  onFill,
  section = false,
  sectionsShown,
  onToggleSections,
}: {
  kind: WorkspaceKind;
  id: string;
  label: string;
  canEdit: boolean;
  canManage?: boolean;
  activeDocumentId: string | null;
  onOpen: (r: OpenRequest) => void;
  onUpload: (folder: string, files?: File[]) => void;
  onFill?: (doc: { document_id: string; title: string }) => void;
  /** A collapsible section under the main root. */
  section?: boolean;
  sectionsShown?: boolean;
  onToggleSections?: () => void;
}) {
  const [expanded, setExpanded] = useState(!section);
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const confirm = useConfirm();
  const [asking, setAsking] = useState<Ask | null>(null);
  const [fromTemplate, setFromTemplate] = useState(false);
  const [sort, setSort] = useStored<Sort>("precentis.explorer.sort", "name");
  const [filter, setFilter] = useState("");
  const [tag, setTag] = useState("");
  const [selected, setSelected] = useState<Map<string, WorkspaceDocument>>(new Map());
  const [dropping, setDropping] = useState(false);
  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("workspace") || q.queryKey.includes("document-places") });
  const guarded = async (fn: () => Promise<unknown>) => {
    try {
      await fn();
      await refresh();
    } catch (err) {
      toast(firmError(err));
    }
  };
  const removeFolder = (path: string) =>
    void guarded(async () => {
      if (await confirm({ title: `Delete folder “${path}”?`, description: "Only empty folders can be deleted.", confirmLabel: "Delete folder", destructive: true }))
        await deleteFolder(kind, id, path);
    });
  const unlink = (doc: WorkspaceDocument) =>
    void guarded(async () => {
      if (await confirm({ title: `Remove “${displayTitle(doc.title)}” from this workspace?`, description: "The document itself is not deleted; it stays where it lives.", confirmLabel: "Remove" }))
        await unlinkDocument(doc.document_id, kind, id);
    });
  const archive = (docs: WorkspaceDocument[]) =>
    void guarded(async () => {
      const homes = docs.filter((d) => d.placement === "home");
      const links = docs.filter((d) => d.placement === "link");
      if (!homes.length && links.length === 1) return unlink(links[0]);
      const ok = await confirm({
        title: homes.length === 1 && !links.length ? `Archive “${displayTitle(homes[0].title)}”?` : `Archive ${homes.length} documents?`,
        description:
          "Archived documents leave every workspace and search for everyone. An administrator can restore them from Settings → Archived documents." +
          (links.length ? ` ${links.length} linked ${links.length === 1 ? "document is" : "documents are"} only removed from this workspace.` : ""),
        confirmLabel: "Archive",
        destructive: true,
      });
      if (!ok) return;
      for (const d of homes) await archiveDocument(d.document_id, "Archived from the workbench");
      for (const d of links) await unlinkDocument(d.document_id, kind, id);
      setSelected(new Map());
      toast(homes.length === 1 ? "Archived" : `${homes.length} archived`);
    });
  const moveDoc = (source: DragSource, folder: string) =>
    void guarded(async () => {
      if (source.kind === kind && source.id === id) {
        await placeInFolder(source.documentId, { kind, id, folder });
        toast(folder ? `Moved to ${folder}` : "Moved to the top level");
      } else {
        // From another workspace: not a move. Ask, because the document will show here and keep its own access.
        const ok = await confirm({
          title: `Show “${displayTitle(source.title)}” in ${label} too?`,
          description: "It is not copied or moved: it stays one document with one history, and people here see it only if they can already read it where it lives.",
          confirmLabel: "Add here",
        });
        if (!ok) return;
        await linkDocument(source.documentId, { kind, id, folder });
        toast(`Added to ${label}${folder ? ` / ${folder}` : ""}`);
      }
    });
  const toggleSelected = (doc: WorkspaceDocument) =>
    setSelected((prev) => {
      const next = new Map(prev);
      if (next.has(doc.document_id)) next.delete(doc.document_id);
      else next.set(doc.document_id, doc);
      return next;
    });
  const firmRoot = useWorkspaceItems("firm", "templates", { folder: "", enabled: !section });
  const canCurate = !section && kind !== "firm" && !!firmRoot.data && firmRoot.data.my_level !== "read";
  const copyToTemplates = (doc: WorkspaceDocument) =>
    void guarded(async () => {
      const ok = await confirm({
        title: `Copy “${displayTitle(doc.title)}” into the firm's templates?`,
        description: "Every member will be able to start new documents from the copy. Remove client names and confidential details from it first; the original is not changed.",
        confirmLabel: "Copy into templates",
      });
      if (!ok) return;
      await copyDocument(doc.document_id, { kind: "firm", id: "templates", folder: "" });
      toast("Copied into Firm templates");
    });
  const ctx: Ctx = {
    kind, id, label, canEdit, canManage: canManage && canEdit, canCurate, copyToTemplates, activeDocumentId, sort, selected: new Set(selected.keys()),
    toggleSelected, onOpen, onUpload, ask: setAsking, removeFolder, unlink, archive, moveDoc,
  };
  const close = () => setAsking(null);
  const docAsk = asking && "doc" in asking ? asking : null;
  const manyAsk = asking && "docs" in asking ? asking : null;
  const filtering = !!(filter.trim() || tag);
  const isEmptyLibrary = useWorkspaceItems(kind, id, { folder: "", enabled: kind === "library" && !section });

  // Files dragged from the desktop anywhere on the list upload to the top level (folders take them themselves).
  const onDragOverRoot = (e: DragEvent) => {
    if (!canEdit) return;
    const types = e.dataTransfer.types;
    if (types.includes("Files") || types.includes(DOC_DRAG)) {
      e.preventDefault();
      if (types.includes("Files")) setDropping(true);
    }
  };
  const onDropRoot = (e: DragEvent) => {
    setDropping(false);
    if (!canEdit) return;
    const raw = e.dataTransfer.getData(DOC_DRAG);
    if (raw) {
      e.preventDefault();
      moveDoc(JSON.parse(raw) as DragSource, "");
      return;
    }
    if (e.dataTransfer.files.length) {
      e.preventDefault();
      onUpload("", Array.from(e.dataTransfer.files));
    }
  };

  return (
    <div className={section ? "" : "flex min-h-0 flex-1 flex-col"} data-testid={section ? `explorer-root-${kind}` : "explorer-primary"}>
      <div className={cn("flex items-center gap-1 px-3 py-2", !section && "border-b border-border", section && "hover:bg-secondary/50")}>
        {section ? (
          <button type="button" className="flex min-w-0 flex-1 items-center gap-1 text-left" aria-expanded={expanded}
            onClick={() => setExpanded((e) => !e)} data-testid={`explorer-section-${kind}`}>
            <Icon name={expanded ? "expand_more" : "chevron_right"} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
            <Icon name={kind === "firm" ? "library_books" : "person_book"} className="shrink-0 text-muted-foreground" style={{ fontSize: 15 }} />
            <span className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{label}</span>
          </button>
        ) : (
          <div className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground" title={label}>
            Files
          </div>
        )}
        {(!section || expanded) && canEdit && (
          <>
            <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" onClick={() => onUpload("")} data-testid="explorer-upload" title={ACCEPTED_HINT}>
              <Icon name="upload_file" style={{ fontSize: 16 }} /> Upload
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="sm" className="h-7 px-2 text-xs" data-testid="explorer-new">
                  <Icon name="add" style={{ fontSize: 16 }} /> New
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end" className="w-56">
                <DropdownMenuItem onSelect={() => setAsking({ type: "new-folder", parent: "" })} data-testid="explorer-new-folder">
                  <Icon name="create_new_folder" style={{ fontSize: 16 }} /> Folder
                </DropdownMenuItem>
                {kind !== "firm" && (
                  <DropdownMenuItem onSelect={() => setFromTemplate(true)} data-testid="explorer-from-template">
                    <Icon name="note_add" style={{ fontSize: 16 }} /> Document from a firm template
                  </DropdownMenuItem>
                )}
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        )}
        {!section && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" aria-label="View options" className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" data-testid="explorer-view">
                <Icon name="more_vert" style={{ fontSize: 17 }} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-56">
              <DropdownMenuLabel className="text-xs text-muted-foreground">Sort</DropdownMenuLabel>
              {(["name", "modified", "type"] as const).map((s) => (
                <DropdownMenuItem key={s} onSelect={() => setSort(s)}>
                  {sort === s ? <Icon name="check" style={{ fontSize: 16 }} /> : <span className="inline-block w-4" />}
                  {s === "name" ? "By name" : s === "modified" ? "Newest first" : "By type"}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              {onToggleSections && (
                <DropdownMenuItem onSelect={onToggleSections}>
                  <Icon name={sectionsShown ? "visibility_off" : "visibility"} style={{ fontSize: 16 }} />
                  {sectionsShown ? "Hide My library and templates here" : "Show My library and templates here"}
                </DropdownMenuItem>
              )}
              <DropdownMenuItem onSelect={() => void refresh()}>
                <Icon name="refresh" style={{ fontSize: 16 }} /> Refresh
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>

      {!section && <FilterBar filter={filter} setFilter={setFilter} tag={tag} setTag={setTag} />}

      {!section && selected.size > 0 && (
        <div className="flex flex-wrap items-center gap-1 border-b border-border bg-wine-soft/60 px-3 py-1.5 text-xs" data-testid="explorer-bulk">
          <span className="mr-1 font-medium text-wine">{selected.size} selected</span>
          {canEdit && <BulkButton icon="drive_file_move" label="Move" onClick={() => setAsking({ type: "move", docs: [...selected.values()] })} />}
          <BulkButton icon="add_link" label="Add to…" onClick={() => setAsking({ type: "link-many", docs: [...selected.values()] })} />
          <BulkButton icon="sell" label="Tag" onClick={() => setAsking({ type: "tag-many", docs: [...selected.values()] })} />
          {canManage && canEdit && <BulkButton icon="archive" label="Archive" onClick={() => archive([...selected.values()])} />}
          <button type="button" className="ml-auto text-muted-foreground hover:text-foreground" onClick={() => setSelected(new Map())}>Clear</button>
        </div>
      )}

      {expanded && (
        <div
          className={cn(section ? "py-1" : "relative min-h-0 flex-1 overflow-y-auto py-1", dropping && "bg-wine-soft/40")}
          role="tree"
          aria-label={`${label} files`}
          aria-multiselectable
          onDragOver={onDragOverRoot}
          onDragLeave={(e) => { if (e.currentTarget === e.target) setDropping(false); }}
          onDrop={onDropRoot}
          onKeyDown={treeKeys}
          data-testid={section ? undefined : "explorer-tree"}
        >
          {dropping && !section && (
            <div className="pointer-events-none absolute inset-2 z-10 flex items-center justify-center rounded-md border-2 border-dashed border-wine/60 text-sm text-wine">
              Drop to upload to {label}
            </div>
          )}
          {filtering && !section ? (
            <FilteredList ctx={ctx} q={filter} tag={tag} />
          ) : kind === "library" && !section && isEmptyLibrary.data && isEmptyLibrary.data.total === 0 && isEmptyLibrary.data.folders.length === 0 ? (
            <>
              <LibraryWelcome canEdit={canEdit} onUpload={() => onUpload("")} onTemplate={() => setFromTemplate(true)} />
              <SharedWithMe ctx={ctx} />
            </>
          ) : (
            <>
              <FolderContents ctx={ctx} folder="" depth={0} />
              {kind === "library" && !section && <SharedWithMe ctx={ctx} />}
            </>
          )}
        </div>
      )}

      <NewFromTemplateDialog kind={kind} id={id} open={fromTemplate} onOpenChange={setFromTemplate} canFill={!!onFill}
        onCreated={(d, fill) => {
          void refresh();
          toast("Created from the template — it is your own copy");
          onOpen({ documentId: d.document_id, title: d.title });
          if (fill) onFill?.(d);
        }} />
      <PromptDialog
        open={asking?.type === "new-folder"}
        onOpenChange={(o) => !o && close()}
        title="New folder"
        label="Folder name"
        hint={asking?.type === "new-folder" && asking.parent ? `Inside ${asking.parent}` : undefined}
        confirm="Create folder"
        onConfirm={async (name) => {
          const parent = asking?.type === "new-folder" ? asking.parent : "";
          await createFolder(kind, id, parent ? `${parent}/${name.replace(/\//g, "-")}` : name.replace(/\//g, "-"));
          await refresh();
        }}
      />
      <RenameOrMoveFolder kind={kind} id={id} path={asking?.type === "rename-folder" ? asking.path : null} onClose={close}
        onDone={() => void refresh()} />
      <PromptDialog
        open={asking?.type === "rename"}
        onOpenChange={(o) => !o && close()}
        title="Rename document"
        label="Name"
        hint="Only the name changes; the file and its versions stay as they are."
        initial={asking?.type === "rename" ? asking.doc.title : ""}
        confirm="Rename"
        onConfirm={async (title) => {
          if (asking?.type !== "rename") return;
          await renameDocument(asking.doc.document_id, title);
          await queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(asking.doc.document_id) });
          await refresh();
        }}
      />
      <MoveDialog kind={kind} id={id} docs={asking?.type === "move" ? asking.docs : null} onClose={close}
        onDone={(n, folder) => { void refresh(); toast(`${n === 1 ? "Moved" : `${n} moved`} to ${folder || "the top level"}`); setSelected(new Map()); }} />
      <TargetDialog
        open={asking?.type === "link" || asking?.type === "link-many"}
        onOpenChange={(o) => !o && close()}
        title={manyAsk && asking?.type === "link-many" ? `Show ${manyAsk.docs.length} documents in another workspace` : "Show in another workspace"}
        description="Nothing is copied: the document shows in both places and stays one document with one history. People there see it only if they can already read it where it lives."
        confirm="Add"
        kinds={["project", "matter", "library"]}
        exclude={{ kind, id }}
        onConfirm={async (t: TargetChoice) => {
          const docs = asking?.type === "link-many" ? asking.docs : docAsk ? [docAsk.doc] : [];
          for (const d of docs) await linkDocument(d.document_id, t);
          await refresh();
          setSelected(new Map());
          toast(docs.length === 1 ? "Added — it is the same document in both places" : `${docs.length} added`);
        }}
      />
      <TargetDialog
        open={asking?.type === "copy"}
        onOpenChange={(o) => !o && close()}
        title="Make a copy"
        description="A separate document with its own history, starting from the current version. Use this for a draft that should go its own way."
        confirm="Make copy"
        kinds={["library", "project", "matter"]}
        askTitle
        defaultTitle={docAsk ? `${docAsk.doc.title}` : ""}
        onConfirm={async (t: TargetChoice) => {
          if (!docAsk) return;
          const made = await copyDocument(docAsk.doc.document_id, t);
          await refresh();
          toast("Copy made");
          if (t.kind === kind && t.id === id) onOpen({ documentId: made.document_id, title: made.title });
        }}
      />
      <TargetDialog
        open={asking?.type === "file"}
        onOpenChange={(o) => !o && close()}
        title={docAsk?.doc.home_kind === "library" ? "Move it to a matter or project" : "File it into a matter"}
        description="Its new home decides who can read it from now on. It stays visible here as a link."
        confirm="Move"
        kinds={docAsk?.doc.home_kind === "library" ? ["matter", "project"] : ["matter"]}
        onConfirm={async (t: TargetChoice) => {
          if (!docAsk) return;
          await moveHome(docAsk.doc.document_id, t);
          await refresh();
          toast(t.kind === "matter" ? "Filed into the matter" : "Moved to the project");
        }}
      />
      <PromptDialog
        open={asking?.type === "tag-many"}
        onOpenChange={(o) => !o && close()}
        title={manyAsk ? `Tag ${manyAsk.docs.length} documents` : "Tag"}
        label="Tag"
        confirm="Add tag"
        onConfirm={async (t) => {
          if (asking?.type !== "tag-many") return;
          let failed = 0;
          for (const d of asking.docs) await addTag(d.document_id, t).catch(() => { failed += 1; });
          await refresh();
          setSelected(new Map());
          toast(failed ? `Tagged ${asking.docs.length - failed}; ${failed} you cannot edit` : `Tagged ${asking.docs.length}`);
        }}
      />
      {docAsk?.type === "tags" && (
        <TagsDialog documentId={docAsk.doc.document_id} open onOpenChange={(o) => !o && close()} onChanged={() => void refresh()} />
      )}
      {docAsk?.type === "share" && (
        <LibraryShareDialog documentId={docAsk.doc.document_id} title={displayTitle(docAsk.doc.title)} open onOpenChange={(o) => !o && close()} />
      )}
    </div>
  );
}

/** Arrow keys move between rows, → / ← open and close folders (WAI-ARIA tree pattern, simplified). */
function treeKeys(e: ReactKeyboardEvent<HTMLDivElement>) {
  const rowsInTree = Array.from(e.currentTarget.querySelectorAll<HTMLElement>("[data-tree-row]"));
  const at = rowsInTree.indexOf(document.activeElement as HTMLElement);
  if (at < 0) return;
  const go = (i: number) => rowsInTree[Math.max(0, Math.min(rowsInTree.length - 1, i))]?.focus();
  if (e.key === "ArrowDown") go(at + 1);
  else if (e.key === "ArrowUp") go(at - 1);
  else if (e.key === "Home") go(0);
  else if (e.key === "End") go(rowsInTree.length - 1);
  else return;
  e.preventDefault();
}

function BulkButton({ icon, label, onClick }: { icon: string; label: string; onClick: () => void }) {
  return (
    <button type="button" onClick={onClick} className="flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-card">
      <Icon name={icon} style={{ fontSize: 14 }} /> {label}
    </button>
  );
}

function FilterBar({ filter, setFilter, tag, setTag }: { filter: string; setFilter: (v: string) => void; tag: string; setTag: (v: string) => void }) {
  const tags = useTagSuggestions("");
  return (
    <div className="flex items-center gap-1.5 border-b border-border px-3 py-1.5">
      <div className="relative min-w-0 flex-1">
        <Icon name="filter_list" className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-muted-foreground" style={{ fontSize: 15 }} />
        <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name" aria-label="Filter by name"
          className="w-full rounded-md border border-border bg-card py-1 pl-7 pr-2 text-xs focus-visible:border-wine/60 focus-visible:outline-none"
          data-testid="explorer-filter" />
      </div>
      {(tags.data ?? []).length > 0 && (
        <select value={tag} onChange={(e) => setTag(e.target.value)} aria-label="Filter by tag" data-testid="explorer-tag-filter"
          className={cn("max-w-[110px] rounded-md border border-border bg-card px-1.5 py-1 text-xs", tag && "border-wine/60 text-wine")}>
          <option value="">Any tag</option>
          {(tags.data ?? []).map((t) => <option key={t.tag} value={t.tag}>#{t.tag}</option>)}
        </select>
      )}
      {(filter || tag) && (
        <button type="button" onClick={() => { setFilter(""); setTag(""); }} className="text-xs text-wine hover:underline">Clear</button>
      )}
    </div>
  );
}

/** Name or tag filter: every matching document of the workspace, with its folder. */
function FilteredList({ ctx, q, tag }: { ctx: Ctx; q: string; tag: string }) {
  const query = useDebounced(q.trim(), 200);
  const items = useWorkspaceItems(ctx.kind, ctx.id, { recursive: true, q: query, tag: tag || undefined });
  if (items.isPending) return <RowNote depth={0}>Searching…</RowNote>;
  if (items.isError) return <RowNote depth={0} error>Could not search. <RetryLink onClick={() => void items.refetch()} /></RowNote>;
  const docs = sorted(items.data.documents, ctx.sort).filter((d): d is WorkspaceDocument => !d.restricted);
  if (!docs.length) return <RowNote depth={0}>Nothing here matches{tag ? ` #${tag}` : ""}{query ? ` “${query}”` : ""}.</RowNote>;
  return <div role="group">{docs.map((d) => <DocumentRow key={d.document_id + d.folder} ctx={ctx} doc={d} depth={0} showFolder />)}</div>;
}

function LibraryWelcome({ canEdit, onUpload, onTemplate }: { canEdit: boolean; onUpload: () => void; onTemplate: () => void }) {
  return (
    <div className="mx-3 my-3 space-y-3 rounded-md border border-dashed border-border px-4 py-5 text-sm" data-testid="library-welcome">
      <div className="font-medium text-foreground">Your own files</div>
      <ul className="space-y-1.5 text-xs text-muted-foreground">
        <li>Drafts, notes and research that do not belong to a matter yet.</li>
        <li>Only you see them, plus anyone you share a file with.</li>
        <li>They are never in firm search or Ask the Firm. File one into a matter when it is ready.</li>
      </ul>
      {canEdit && (
        <div className="flex flex-wrap gap-2">
          <Button size="sm" onClick={onUpload}><Icon name="upload_file" style={{ fontSize: 16 }} /> Upload files</Button>
          <Button size="sm" variant="outline" onClick={onTemplate}>From a template</Button>
        </div>
      )}
      <p className="text-xs text-muted-foreground">You can also drop files here. {ACCEPTED_HINT}.</p>
    </div>
  );
}

/** Files colleagues shared with you from their libraries (listed in your library, under their own heading). */
function SharedWithMe({ ctx }: { ctx: Ctx }) {
  const shared = useSharedWithMe();
  const [open, setOpen] = useState(true);
  const docs = shared.data ?? [];
  if (!docs.length) return null;
  const readOnly = { ...ctx, canEdit: false, canManage: false, canCurate: false };
  return (
    <div className="mt-2 border-t border-border pt-1" data-testid="shared-with-me">
      <button type="button" className="flex w-full items-center gap-1 px-3 py-1 text-left" aria-expanded={open} onClick={() => setOpen((o) => !o)}>
        <Icon name={open ? "expand_more" : "chevron_right"} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
        <span className="text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Shared with me</span>
        <span className="ml-1 font-mono-id text-[11px] text-muted-foreground">{docs.length}</span>
      </button>
      {open && docs.map((d) => <DocumentRow key={d.document_id} ctx={readOnly} doc={d} depth={0} note={d.owner_name ? `from ${d.owner_name}` : undefined} />)}
    </div>
  );
}

const PAGE = 200;

function FolderContents({ ctx, folder, depth }: { ctx: Ctx; folder: string; depth: number }) {
  const [pages, setPages] = useState(1);
  const items = useWorkspaceItems(ctx.kind, ctx.id, { folder, limit: PAGE });
  if (items.isPending) return <RowNote depth={depth}>Loading…</RowNote>;
  if (items.isError) return <RowNote depth={depth} error>Could not load this folder. <RetryLink onClick={() => void items.refetch()} /></RowNote>;
  const data = items.data;
  if (depth === 0 && data.folders.length === 0 && data.documents.length === 0) {
    return (
      <div className="mx-3 my-3 rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground" data-testid="explorer-empty">
        {ctx.kind === "firm"
          ? ctx.canEdit
            ? "No templates yet. Upload Word files here, or open a matter and use “Copy into firm templates” on a document that makes a good starting point."
            : "No templates yet. Your knowledge managers add them; ask them for the ones you need."
          : ctx.canEdit ? "Nothing here yet. Upload files or drop them here." : "Nothing here yet."}
      </div>
    );
  }
  return (
    <div role="group">
      {data.folders.map((f) => <FolderNode key={f.path} ctx={ctx} folder={f} depth={depth} />)}
      {sorted(data.documents, ctx.sort).map((d, i) => <DocumentNode key={d.restricted ? `r${d.link_id}` : d.document_id + i} ctx={ctx} item={d} depth={depth} />)}
      {Array.from({ length: pages - 1 }, (_, i) => <MorePage key={i} ctx={ctx} folder={folder} depth={depth} offset={(i + 1) * PAGE} />)}
      {data.total > pages * PAGE && (
        <button type="button" onClick={() => setPages((p) => p + 1)} className="py-1 text-xs font-medium text-wine hover:underline"
          style={{ paddingLeft: 26 + depth * 14 }} data-testid="explorer-more">
          Show more ({data.total - pages * PAGE} more in this folder)
        </button>
      )}
    </div>
  );
}

function MorePage({ ctx, folder, depth, offset }: { ctx: Ctx; folder: string; depth: number; offset: number }) {
  const items = useWorkspaceItems(ctx.kind, ctx.id, { folder, limit: PAGE, offset });
  if (items.isPending) return <RowNote depth={depth}>Loading…</RowNote>;
  return <>{sorted(items.data?.documents ?? [], ctx.sort).map((d, i) => <DocumentNode key={d.restricted ? `r${d.link_id}` : d.document_id + i} ctx={ctx} item={d} depth={depth} />)}</>;
}

function RowNote({ depth, error, children }: { depth: number; error?: boolean; children: ReactNode }) {
  return <div className={cn("px-3 py-1 text-xs", error ? "text-destructive" : "text-muted-foreground")} style={{ paddingLeft: 12 + depth * 14 }}>{children}</div>;
}

function RetryLink({ onClick }: { onClick: () => void }) {
  return <button type="button" onClick={onClick} className="font-medium underline">Try again</button>;
}

function dropFiles(e: DragEvent, ctx: Ctx, folder: string) {
  if (!ctx.canEdit || !e.dataTransfer.files.length) return;
  e.preventDefault();
  e.stopPropagation();
  ctx.onUpload(folder, Array.from(e.dataTransfer.files));
}

function FolderNode({ ctx, folder, depth }: { ctx: Ctx; folder: WorkspaceFolder; depth: number }) {
  const [open, setOpen] = useState(false);
  const [over, setOver] = useState(false);
  const [menu, setMenu] = useState(false);
  return (
    <div role="none">
      <div
        className={cn("group flex items-center gap-1 py-[3px] pr-2 text-[13px] hover:bg-secondary/70", over && "bg-wine-soft")}
        style={{ paddingLeft: 8 + depth * 14 }}
        onDragOver={(e) => {
          if (ctx.canEdit && (e.dataTransfer.types.includes("Files") || e.dataTransfer.types.includes(DOC_DRAG))) {
            e.preventDefault();
            e.stopPropagation();
            setOver(true);
          }
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          setOver(false);
          const raw = e.dataTransfer.getData(DOC_DRAG);
          if (ctx.canEdit && raw) {
            e.preventDefault();
            e.stopPropagation();
            ctx.moveDoc(JSON.parse(raw) as DragSource, folder.path);
            return;
          }
          dropFiles(e, ctx, folder.path);
        }}
        onContextMenu={(e) => { if (ctx.canEdit) { e.preventDefault(); setMenu(true); } }}
        data-testid="explorer-folder"
      >
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1 text-left" role="treeitem" aria-expanded={open} data-tree-row
          onClick={() => setOpen((o) => !o)}
          onKeyDown={(e) => {
            if (e.key === "ArrowRight" && !open) { e.preventDefault(); e.stopPropagation(); setOpen(true); }
            else if (e.key === "ArrowLeft" && open) { e.preventDefault(); e.stopPropagation(); setOpen(false); }
            else if (e.key === "F2" && ctx.canEdit) { e.preventDefault(); ctx.ask({ type: "rename-folder", path: folder.path }); }
          }}>
          <Icon name={open ? "expand_more" : "chevron_right"} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
          <Icon name={open ? "folder_open" : "folder"} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
          <span className="truncate">{folder.name}</span>
          <span className="ml-1 shrink-0 font-mono-id text-[11px] text-muted-foreground">{folder.document_count || ""}</span>
        </button>
        {ctx.canEdit && (
          <RowMenu label={`Folder ${folder.name} actions`} open={menu} onOpenChange={setMenu}>
            <DropdownMenuItem onSelect={() => ctx.onUpload(folder.path)}>
              <Icon name="upload_file" style={{ fontSize: 16 }} /> Upload here
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => ctx.ask({ type: "new-folder", parent: folder.path })}>
              <Icon name="create_new_folder" style={{ fontSize: 16 }} /> New folder inside
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => ctx.ask({ type: "rename-folder", path: folder.path })}>
              <Icon name="drive_file_rename_outline" style={{ fontSize: 16 }} /> Rename or move…
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => ctx.removeFolder(folder.path)} className="text-destructive">
              <Icon name="delete" style={{ fontSize: 16 }} /> Delete folder
            </DropdownMenuItem>
          </RowMenu>
        )}
      </div>
      {open && <FolderContents ctx={ctx} folder={folder.path} depth={depth + 1} />}
    </div>
  );
}

function DocumentNode({ ctx, item, depth }: { ctx: Ctx; item: WorkspaceItem; depth: number }) {
  if (item.restricted) {
    return (
      <div
        className="flex items-center gap-1.5 py-[3px] pr-2 text-[13px] text-muted-foreground"
        style={{ paddingLeft: 26 + depth * 14 }}
        title="Someone added a document here from a place you cannot open. Ask this workspace's owner, or the matter's team, for access."
        data-testid="explorer-restricted"
        role="treeitem"
      >
        <Icon name="lock" className="shrink-0" style={{ fontSize: 15 }} />
        <span className="truncate italic">Restricted document</span>
        <span className="ml-auto shrink-0 text-[11px]">no access</span>
      </div>
    );
  }
  return <DocumentRow ctx={ctx} doc={item} depth={depth} />;
}

function DocumentRow({ ctx, doc, depth, showFolder, note }: { ctx: Ctx; doc: WorkspaceDocument; depth: number; showFolder?: boolean; note?: string }) {
  const active = ctx.activeDocumentId === doc.document_id;
  const selected = ctx.selected.has(doc.document_id);
  const [menu, setMenu] = useState(false);
  const title = displayTitle(doc.title);
  const open = (e: ReactMouseEvent, preview: boolean) => {
    if (e.metaKey || e.ctrlKey || e.shiftKey) {
      // ⌘/Ctrl-click (or Shift-click) selects, for acting on several documents at once.
      ctx.toggleSelected(doc, e.shiftKey);
      return;
    }
    ctx.onOpen({ documentId: doc.document_id, title: doc.title, preview, toSide: e.altKey });
  };
  const canFile = ctx.canEdit && doc.home_kind !== "matter" && doc.placement === "home";
  const isHome = doc.placement === "home";
  const canShare = ctx.kind === "library" && doc.home_kind === "library" && isHome && ctx.canEdit;
  const details = [doc.updated_at ? `Changed ${formatDate(doc.updated_at)}` : null, doc.version_number ? `version ${doc.version_number}` : null,
    doc.author_name ? `by ${doc.author_name}` : null, doc.placement === "link" ? "shown here from where it lives" : null].filter(Boolean).join(" · ");
  return (
    <div
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DOC_DRAG, JSON.stringify({ documentId: doc.document_id, title: doc.title, kind: ctx.kind, id: ctx.id } satisfies DragSource));
        e.dataTransfer.setData("text/plain", doc.title);
        e.dataTransfer.effectAllowed = "copyMove";
      }}
      onContextMenu={(e) => { e.preventDefault(); setMenu(true); }}
      className={cn(
        "group flex items-center gap-1.5 py-[3px] pr-2 text-[13px]",
        selected ? "bg-wine-soft/70" : active ? "bg-wine-soft text-wine" : "hover:bg-secondary/70",
      )}
      style={{ paddingLeft: 26 + depth * 14 }}
      data-testid="explorer-document"
      data-document-id={doc.document_id}
    >
      <button
        type="button"
        role="treeitem"
        aria-selected={selected}
        aria-current={active ? "true" : undefined}
        data-tree-row
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        onClick={(e) => open(e, true)}
        onDoubleClick={(e) => open(e, false)}
        onKeyDown={(e) => {
          if (e.key === "Enter") { e.preventDefault(); ctx.onOpen({ documentId: doc.document_id, title: doc.title, toSide: e.altKey }); }
          else if (e.key === " ") { e.preventDefault(); ctx.toggleSelected(doc, false); }
          else if (e.key === "F2" && ctx.canEdit) { e.preventDefault(); ctx.ask({ type: "rename", doc }); }
          else if ((e.key === "Delete" || e.key === "Backspace") && (doc.placement === "link" ? ctx.canEdit : ctx.canManage)) { e.preventDefault(); ctx.archive([doc]); }
        }}
        title={`${doc.title}\n${details}`}
      >
        <Icon name={iconFor(doc)} className={cn("shrink-0", active ? "text-wine" : "text-muted-foreground")} style={{ fontSize: 15 }} />
        <span className="truncate">{title}</span>
        {doc.placement === "link" && <Icon name="link" aria-label="Shown here from where it lives" className="shrink-0 text-muted-foreground" style={{ fontSize: 13 }} />}
        {doc.private && <Icon name="lock" aria-label="Private" className="shrink-0 text-muted-foreground" style={{ fontSize: 13 }} />}
        {doc.tags.user.slice(0, 2).map((t) => <span key={t} className="hidden shrink-0 text-[11px] text-muted-foreground sm:inline">#{t}</span>)}
        {/* The date shows when sorting by it; otherwise the title gets the width (details are in the tooltip). */}
        {(note || showFolder || ctx.sort === "modified") && (
          <span className="ml-auto max-w-[45%] shrink-0 truncate pl-2 text-[11px] text-muted-foreground">
            {note ?? (showFolder ? doc.folder || "" : doc.updated_at ? formatDate(doc.updated_at) : "")}
          </span>
        )}
      </button>
      <RowMenu label={`${title} actions`} open={menu} onOpenChange={setMenu}>
        <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title })}>
          <Icon name="open_in_new" style={{ fontSize: 16 }} /> Open
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title, toSide: true })}>
          <Icon name="vertical_split" style={{ fontSize: 16 }} /> Open to the side
        </DropdownMenuItem>
        {/word|docx/i.test((doc.mime_type ?? "") + doc.title) && (
          <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title, write: true })} data-testid="explorer-edit-word">
            <Icon name="edit_document" style={{ fontSize: 16 }} /> Edit in Word
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => void downloadDocument(doc.document_id)}>
          <Icon name="download" style={{ fontSize: 16 }} /> Download
        </DropdownMenuItem>
        {ctx.canEdit && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "rename", doc })} data-testid="explorer-rename">
            <Icon name="drive_file_rename_outline" style={{ fontSize: 16 }} /> Rename
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        {canShare && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "share", doc })} data-testid="explorer-share">
            <Icon name="person_add" style={{ fontSize: 16 }} /> Share with people…
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "link", doc })}>
          <Icon name="add_link" style={{ fontSize: 16 }} /> Show in another workspace…
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "copy", doc })}>
          <Icon name="content_copy" style={{ fontSize: 16 }} /> Make a copy…
        </DropdownMenuItem>
        {canFile && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "file", doc })}>
            <Icon name="gavel" style={{ fontSize: 16 }} /> {doc.home_kind === "library" ? "Move to a matter or project…" : "File into a matter…"}
          </DropdownMenuItem>
        )}
        {ctx.canEdit && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "move", docs: [doc] })}>
            <Icon name="drive_file_move" style={{ fontSize: 16 }} /> Move to folder…
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "tags", doc })}>
          <Icon name="sell" style={{ fontSize: 16 }} /> Tags…
        </DropdownMenuItem>
        {ctx.canCurate && (
          <DropdownMenuItem onSelect={() => ctx.copyToTemplates(doc)} data-testid="explorer-to-templates">
            <Icon name="library_add" style={{ fontSize: 16 }} /> Copy into firm templates…
          </DropdownMenuItem>
        )}
        {ctx.canEdit && (
          <>
            <DropdownMenuSeparator />
            {doc.placement === "link" ? (
              <DropdownMenuItem onSelect={() => ctx.unlink(doc)}>
                <Icon name="link_off" style={{ fontSize: 16 }} /> Remove from this workspace
              </DropdownMenuItem>
            ) : ctx.canManage && (
              <DropdownMenuItem onSelect={() => ctx.archive([doc])} className="text-destructive" data-testid="explorer-archive">
                <Icon name="archive" style={{ fontSize: 16 }} /> Archive
              </DropdownMenuItem>
            )}
          </>
        )}
      </RowMenu>
    </div>
  );
}

function RowMenu({ label, open, onOpenChange, children }: { label: string; open?: boolean; onOpenChange?: (o: boolean) => void; children: ReactNode }) {
  return (
    <DropdownMenu open={open} onOpenChange={onOpenChange}>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="shrink-0 rounded p-0.5 text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100 [@media(hover:none)]:opacity-100"
        >
          <Icon name="more_horiz" style={{ fontSize: 16 }} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">{children}</DropdownMenuContent>
    </DropdownMenu>
  );
}

/** Move one or more documents to a folder of this workspace, picked from the folder tree. */
function MoveDialog({ kind, id, docs, onClose, onDone }: {
  kind: WorkspaceKind; id: string; docs: WorkspaceDocument[] | null; onClose: () => void; onDone: (n: number, folder: string) => void;
}) {
  const [folder, setFolder] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (docs) {
      setFolder(docs.length === 1 ? docs[0].folder : "");
      setError(null);
    }
  }, [docs]);
  return (
    <Dialog open={!!docs} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="move-dialog">
        <DialogHeader>
          <DialogTitle>{docs && docs.length > 1 ? `Move ${docs.length} documents` : "Move to folder"}</DialogTitle>
          <DialogDescription>Choose a folder of this workspace.</DialogDescription>
        </DialogHeader>
        <FolderPicker kind={kind} id={id} value={folder} onChange={setFolder} />
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={busy} data-testid="move-confirm" onClick={async () => {
            if (!docs) return;
            setBusy(true);
            setError(null);
            try {
              for (const d of docs) await placeInFolder(d.document_id, { kind, id, folder });
              onDone(docs.length, folder);
              onClose();
            } catch (err) {
              setError(firmError(err));
            } finally {
              setBusy(false);
            }
          }}>Move</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Rename a folder, or move it (with everything in it) inside another folder. */
function RenameOrMoveFolder({ kind, id, path, onClose, onDone }: {
  kind: WorkspaceKind; id: string; path: string | null; onClose: () => void; onDone: () => void;
}) {
  const [name, setName] = useState("");
  const [parent, setParent] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (path) {
      const parts = path.split("/");
      setName(parts.pop() ?? "");
      setParent(parts.join("/"));
      setError(null);
    }
  }, [path]);
  const target = parent ? `${parent}/${name.trim().replace(/\//g, "-")}` : name.trim().replace(/\//g, "-");
  const inside = !!path && (parent === path || parent.startsWith(`${path}/`));
  return (
    <Dialog open={!!path} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="rename-folder-dialog">
        <DialogHeader>
          <DialogTitle>Rename or move folder</DialogTitle>
          <DialogDescription>Everything in the folder moves with it.</DialogDescription>
        </DialogHeader>
        <label className="block space-y-1 text-sm font-medium">
          <span>Name</span>
          <input value={name} onChange={(e) => setName(e.target.value)} maxLength={120} autoFocus
            className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm font-normal" data-testid="rename-folder-name" />
        </label>
        <FolderPicker kind={kind} id={id} value={parent} onChange={setParent} label="Inside" />
        {inside && <p className="text-sm text-destructive">A folder cannot go inside itself.</p>}
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>Cancel</Button>
          <Button disabled={busy || !name.trim() || inside || target === path} data-testid="rename-folder-confirm" onClick={async () => {
            if (!path) return;
            setBusy(true);
            setError(null);
            try {
              await renameFolder(kind, id, path, target);
              onDone();
              onClose();
            } catch (err) {
              setError(firmError(err));
            } finally {
              setBusy(false);
            }
          }}>Save</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
