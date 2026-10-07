import { useState, type DragEvent, type MouseEvent as ReactMouseEvent, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import {
  copyDocument,
  createFolder,
  deleteFolder,
  linkDocument,
  moveHome,
  placeInFolder,
  renameFolder,
  unlinkDocument,
  useWorkspaceItems,
  type WorkspaceDocument,
  type WorkspaceFolder,
  type WorkspaceItem,
  type WorkspaceKind,
} from "@/api/workspaces";
import { copyContentFrom } from "@/api/editor";
import { useConfirm } from "@/components/common/Confirm";
import { Icon } from "@/components/common/primitives";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";
import { NewFromTemplateDialog, PromptDialog, TagsDialog, TargetDialog, type TargetChoice } from "./dialogs";

export type OpenRequest = { documentId: string; title: string; preview?: boolean; toSide?: boolean; params?: string; write?: boolean };

type Ctx = {
  kind: WorkspaceKind;
  id: string;
  canEdit: boolean;
  activeDocumentId: string | null;
  onOpen: (r: OpenRequest) => void;
  onUpload: (folder: string, files?: File[]) => void;
  ask: (a: Ask) => void;
  removeFolder: (path: string) => void;
  unlink: (doc: WorkspaceDocument) => void;
  /** A document dragged onto a folder (or the top level): file it there. */
  moveDoc: (documentId: string, folder: string) => void;
  /** A document dragged onto another document: replace the target's content with it (after a confirmation). */
  replaceFrom: (source: { documentId: string; title: string }, target: WorkspaceDocument) => void;
};

const DOC_DRAG = "application/x-precentis-explorer-doc";

type Ask =
  | { type: "new-folder"; parent: string }
  | { type: "rename-folder"; path: string }
  | { type: "move"; doc: WorkspaceDocument }
  | { type: "link" | "copy" | "file"; doc: WorkspaceDocument }
  | { type: "tags"; doc: WorkspaceDocument };

export function iconFor(doc: { mime_type?: string | null; title?: string }): string {
  const t = (doc.mime_type ?? "") + (doc.title ?? "").toLowerCase();
  if (t.includes("pdf")) return "picture_as_pdf";
  if (t.includes("word") || t.includes(".docx")) return "article";
  if (t.includes("sheet") || t.includes(".xlsx") || t.includes(".csv")) return "table_chart";
  return "description";
}

/** The workspace's folders and documents (home and linked), with the actions a workbench needs. */
export function Explorer({
  kind,
  id,
  label,
  canEdit,
  activeDocumentId,
  onOpen,
  onUpload,
}: {
  kind: WorkspaceKind;
  id: string;
  label: string;
  canEdit: boolean;
  activeDocumentId: string | null;
  onOpen: (r: OpenRequest) => void;
  onUpload: (folder: string, files?: File[]) => void;
}) {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const confirm = useConfirm();
  const [asking, setAsking] = useState<Ask | null>(null);
  const [fromTemplate, setFromTemplate] = useState(false);
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
      if (await confirm({ title: `Remove “${doc.title}” from this workspace?`, description: "The document itself is not deleted; it stays where it lives.", confirmLabel: "Remove" }))
        await unlinkDocument(doc.document_id, kind, id);
    });
  const moveDoc = (documentId: string, folder: string) =>
    void guarded(async () => {
      await placeInFolder(documentId, { kind, id, folder });
      toast(folder ? `Moved to ${folder}` : "Moved to the top level");
    });
  const replaceFrom = (source: { documentId: string; title: string }, target: WorkspaceDocument) =>
    void guarded(async () => {
      const ok = await confirm({
        title: `Replace the content of “${target.title}”?`,
        description:
          `“${target.title}” gets a new version with the content of “${source.title}”. ` +
          `“${source.title}” is not changed and keeps its own history; the earlier versions of “${target.title}” stay in its history and can be restored.`,
        confirmLabel: "Replace content",
      });
      if (!ok) return;
      const out = await copyContentFrom(target.document_id, { source_document_id: source.documentId });
      toast(`“${target.title}” is now version ${out.version_number}, with the content of “${source.title}”`);
    });
  const ctx: Ctx = { kind, id, canEdit, activeDocumentId, onOpen, onUpload, ask: setAsking, removeFolder, unlink, moveDoc, replaceFrom };
  const close = () => setAsking(null);

  const docAsk = asking && "doc" in asking ? asking : null;

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-explorer">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground" title={label}>
          {label}
        </div>
        {canEdit && (
          <>
            <IconButton icon="upload_file" label="Upload files" onClick={() => onUpload("")} testId="explorer-upload" />
            <IconButton icon="create_new_folder" label="New folder" onClick={() => setAsking({ type: "new-folder", parent: "" })} testId="explorer-new-folder" />
            {kind !== "firm" && <IconButton icon="note_add" label="New from template" onClick={() => setFromTemplate(true)} testId="explorer-from-template" />}
          </>
        )}
        <IconButton icon="refresh" label="Refresh" onClick={() => void refresh()} />
      </div>
      <div
        className="min-h-0 flex-1 overflow-y-auto py-1"
        role="tree"
        aria-label={`${label} files`}
        onDragOver={(e) => { if (canEdit && e.dataTransfer.types.includes(DOC_DRAG)) e.preventDefault(); }}
        onDrop={(e) => {
          const raw = e.dataTransfer.getData(DOC_DRAG);
          if (!canEdit || !raw) return;
          e.preventDefault();
          moveDoc((JSON.parse(raw) as { documentId: string }).documentId, "");
        }}
      >
        <FolderContents ctx={ctx} folder="" depth={0} />
      </div>

      <NewFromTemplateDialog kind={kind} id={id} open={fromTemplate} onOpenChange={setFromTemplate}
        onCreated={(d) => { void refresh(); toast("Created from the template — it is your own copy"); onOpen({ documentId: d.document_id, title: d.title }); }} />
      <PromptDialog
        open={asking?.type === "new-folder"}
        onOpenChange={(o) => !o && close()}
        title="New folder"
        label="Folder name"
        hint={asking?.type === "new-folder" && asking.parent ? `Inside ${asking.parent}` : undefined}
        confirm="Create folder"
        onConfirm={async (name) => {
          const parent = asking?.type === "new-folder" ? asking.parent : "";
          await createFolder(kind, id, parent ? `${parent}/${name}` : name);
          await refresh();
        }}
      />
      <PromptDialog
        open={asking?.type === "rename-folder"}
        onOpenChange={(o) => !o && close()}
        title="Rename or move folder"
        label="Folder path"
        hint="Use / to move it inside another folder. Everything in it moves too."
        initial={asking?.type === "rename-folder" ? asking.path : ""}
        confirm="Save"
        onConfirm={async (path) => {
          if (asking?.type !== "rename-folder") return;
          await renameFolder(kind, id, asking.path, path);
          await refresh();
        }}
      />
      <PromptDialog
        open={asking?.type === "move"}
        onOpenChange={(o) => !o && close()}
        title="Move to folder"
        label="Folder"
        hint="Leave empty for the top level of this workspace."
        initial={docAsk?.doc.folder ?? ""}
        confirm="Move"
        onConfirm={async (folder) => {
          if (!docAsk) return;
          await placeInFolder(docAsk.doc.document_id, { kind, id, folder });
          await refresh();
        }}
      />
      <TargetDialog
        open={asking?.type === "link"}
        onOpenChange={(o) => !o && close()}
        title="Add to another workspace"
        description="The document is not copied: it shows in both places and stays one document with one history. People there see it only if they can already read it."
        confirm="Add"
        kinds={["project", "matter", "library"]}
        exclude={{ kind, id }}
        onConfirm={async (t: TargetChoice) => {
          if (!docAsk) return;
          await linkDocument(docAsk.doc.document_id, t);
          await refresh();
          toast("Added — it is the same document in both places");
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
        title={docAsk?.doc.home_kind === "library" ? "Move to a matter or project" : "File into a matter"}
        description="The matter becomes the document's home and its access rules apply from now on. It stays visible here as a link."
        confirm="File"
        kinds={docAsk?.doc.home_kind === "library" ? ["matter", "project"] : ["matter"]}
        onConfirm={async (t: TargetChoice) => {
          if (!docAsk) return;
          await moveHome(docAsk.doc.document_id, t);
          await refresh();
          toast(t.kind === "matter" ? "Filed into the matter" : "Moved");
        }}
      />
      {docAsk?.type === "tags" && (
        <TagsDialog documentId={docAsk.doc.document_id} open onOpenChange={(o) => !o && close()} onChanged={() => void refresh()} />
      )}
    </div>
  );
}

function FolderContents({ ctx, folder, depth }: { ctx: Ctx; folder: string; depth: number }) {
  const items = useWorkspaceItems(ctx.kind, ctx.id, { folder });
  if (items.isPending) return <div className="px-3 py-1 text-xs text-muted-foreground" style={{ paddingLeft: 12 + depth * 14 }}>Loading…</div>;
  if (items.isError) return <div className="px-3 py-1 text-xs text-destructive" style={{ paddingLeft: 12 + depth * 14 }}>Could not load this folder</div>;
  const data = items.data;
  if (depth === 0 && data.folders.length === 0 && data.documents.length === 0) {
    return (
      <div
        className="mx-3 my-3 rounded-md border border-dashed border-border px-3 py-6 text-center text-xs text-muted-foreground"
        onDragOver={(e) => ctx.canEdit && e.preventDefault()}
        onDrop={(e) => dropFiles(e, ctx, "")}
      >
        {ctx.canEdit ? "Nothing here yet. Upload files or drop them here." : "Nothing here yet."}
      </div>
    );
  }
  return (
    <div role="group">
      {data.folders.map((f) => <FolderNode key={f.path} ctx={ctx} folder={f} depth={depth} />)}
      {data.documents.map((d, i) => <DocumentNode key={d.restricted ? `r${d.link_id}` : d.document_id + i} ctx={ctx} item={d} depth={depth} />)}
    </div>
  );
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
  return (
    <div role="treeitem" aria-expanded={open} aria-selected={false}>
      <div
        className={cn("group flex items-center gap-1 py-[3px] pr-2 text-[13px] hover:bg-secondary/70", over && "bg-wine-soft")}
        style={{ paddingLeft: 8 + depth * 14 }}
        onDragOver={(e) => {
          if (ctx.canEdit && (e.dataTransfer.types.includes("Files") || e.dataTransfer.types.includes(DOC_DRAG))) {
            e.preventDefault();
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
            ctx.moveDoc((JSON.parse(raw) as { documentId: string }).documentId, folder.path);
            return;
          }
          dropFiles(e, ctx, folder.path);
        }}
        data-testid="explorer-folder"
      >
        <button type="button" className="flex min-w-0 flex-1 items-center gap-1 text-left" onClick={() => setOpen((o) => !o)}>
          <Icon name={open ? "expand_more" : "chevron_right"} className="text-muted-foreground" style={{ fontSize: 16 }} />
          <Icon name={open ? "folder_open" : "folder"} className="text-muted-foreground" style={{ fontSize: 16 }} />
          <span className="truncate">{folder.name}</span>
          <span className="ml-1 font-mono-id text-[11px] text-muted-foreground">{folder.document_count || ""}</span>
        </button>
        {ctx.canEdit && (
          <RowMenu label={`Folder ${folder.name} actions`}>
            <DropdownMenuItem onSelect={() => ctx.onUpload(folder.path)}>
              <Icon name="upload_file" style={{ fontSize: 16 }} /> Upload here
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => ctx.ask({ type: "new-folder", parent: folder.path })}>
              <Icon name="create_new_folder" style={{ fontSize: 16 }} /> New folder inside
            </DropdownMenuItem>
            <DropdownMenuItem onSelect={() => ctx.ask({ type: "rename-folder", path: folder.path })}>
              <Icon name="drive_file_rename_outline" style={{ fontSize: 16 }} /> Rename or move
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
        role="treeitem"
        aria-selected={false}
        className="flex items-center gap-1.5 py-[3px] pr-2 text-[13px] text-muted-foreground"
        style={{ paddingLeft: 26 + depth * 14 }}
        title="A document linked here that you cannot open. Ask the person who added it."
        data-testid="explorer-restricted"
      >
        <Icon name="lock" style={{ fontSize: 15 }} />
        <span className="truncate italic">Restricted document</span>
      </div>
    );
  }
  return <DocumentRow ctx={ctx} doc={item} depth={depth} />;
}

function DocumentRow({ ctx, doc, depth }: { ctx: Ctx; doc: WorkspaceDocument; depth: number }) {
  const active = ctx.activeDocumentId === doc.document_id;
  const open = (e: ReactMouseEvent, preview: boolean) =>
    ctx.onOpen({ documentId: doc.document_id, title: doc.title, preview, toSide: e.altKey || e.metaKey || e.ctrlKey });
  const canFile = ctx.canEdit && doc.home_kind !== "matter" && doc.placement === "home";
  const [over, setOver] = useState(false);
  return (
    <div
      role="treeitem"
      aria-selected={active}
      draggable
      onDragStart={(e) => {
        e.dataTransfer.setData(DOC_DRAG, JSON.stringify({ documentId: doc.document_id, title: doc.title }));
        e.dataTransfer.setData("text/plain", doc.title);
        e.dataTransfer.effectAllowed = "copyMove";
      }}
      onDragOver={(e) => {
        if (ctx.canEdit && e.dataTransfer.types.includes(DOC_DRAG)) {
          e.preventDefault();
          e.stopPropagation();
          setOver(true);
        }
      }}
      onDragLeave={() => setOver(false)}
      onDrop={(e) => {
        setOver(false);
        const raw = e.dataTransfer.getData(DOC_DRAG);
        if (!ctx.canEdit || !raw) return;
        e.preventDefault();
        e.stopPropagation();
        const source = JSON.parse(raw) as { documentId: string; title: string };
        if (source.documentId !== doc.document_id) ctx.replaceFrom(source, doc);
      }}
      className={cn(
        "group flex items-center gap-1.5 py-[3px] pr-2 text-[13px]",
        active ? "bg-wine-soft text-wine" : "hover:bg-secondary/70",
        over && "outline outline-1 -outline-offset-1 outline-wine",
      )}
      style={{ paddingLeft: 26 + depth * 14 }}
      data-testid="explorer-document"
      data-document-id={doc.document_id}
    >
      <button
        type="button"
        className="flex min-w-0 flex-1 items-center gap-1.5 text-left"
        onClick={(e) => open(e, true)}
        onDoubleClick={(e) => open(e, false)}
        title={`${doc.title}${doc.placement === "link" ? " — linked from where it lives" : ""}`}
      >
        <Icon name={iconFor(doc)} className={active ? "text-wine" : "text-muted-foreground"} style={{ fontSize: 15 }} />
        <span className="truncate">{doc.title}</span>
        {doc.placement === "link" && <Icon name="link" aria-label="Linked" className="shrink-0 text-muted-foreground" style={{ fontSize: 13 }} />}
        {doc.private && <Icon name="lock" aria-label="Private" className="shrink-0 text-muted-foreground" style={{ fontSize: 13 }} />}
        {doc.tags.user.length > 0 && <span className="truncate text-[11px] text-muted-foreground">#{doc.tags.user[0]}</span>}
      </button>
      <RowMenu label={`${doc.title} actions`}>
        <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title })}>
          <Icon name="open_in_new" style={{ fontSize: 16 }} /> Open
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title, toSide: true })}>
          <Icon name="vertical_split" style={{ fontSize: 16 }} /> Open to the side
        </DropdownMenuItem>
        {/word|docx/i.test((doc.mime_type ?? "") + doc.title) && (
          <DropdownMenuItem onSelect={() => ctx.onOpen({ documentId: doc.document_id, title: doc.title, write: true })} data-testid="explorer-edit-word">
            <Icon name="edit_document" style={{ fontSize: 16 }} /> Edit in the Word editor
          </DropdownMenuItem>
        )}
        <DropdownMenuSeparator />
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "link", doc })}>
          <Icon name="add_link" style={{ fontSize: 16 }} /> Add to another workspace…
        </DropdownMenuItem>
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "copy", doc })}>
          <Icon name="content_copy" style={{ fontSize: 16 }} /> Make a copy…
        </DropdownMenuItem>
        {canFile && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "file", doc })}>
            <Icon name="gavel" style={{ fontSize: 16 }} /> {doc.home_kind === "library" ? "Move to matter or project…" : "File into a matter…"}
          </DropdownMenuItem>
        )}
        {ctx.canEdit && (
          <DropdownMenuItem onSelect={() => ctx.ask({ type: "move", doc })}>
            <Icon name="drive_file_move" style={{ fontSize: 16 }} /> Move to folder…
          </DropdownMenuItem>
        )}
        <DropdownMenuItem onSelect={() => ctx.ask({ type: "tags", doc })}>
          <Icon name="sell" style={{ fontSize: 16 }} /> Tags…
        </DropdownMenuItem>
        {ctx.canEdit && doc.placement === "link" && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem onSelect={() => ctx.unlink(doc)}>
              <Icon name="link_off" style={{ fontSize: 16 }} /> Remove from this workspace
            </DropdownMenuItem>
          </>
        )}
      </RowMenu>
    </div>
  );
}

function RowMenu({ label, children }: { label: string; children: ReactNode }) {
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          aria-label={label}
          className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-secondary hover:text-foreground focus-visible:opacity-100 group-hover:opacity-100 data-[state=open]:opacity-100"
        >
          <Icon name="more_horiz" style={{ fontSize: 16 }} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-60">{children}</DropdownMenuContent>
    </DropdownMenu>
  );
}

function IconButton({ icon, label, onClick, testId }: { icon: string; label: string; onClick: () => void; testId?: string }) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      onClick={onClick}
      className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
      data-testid={testId}
    >
      <Icon name={icon} style={{ fontSize: 17 }} />
    </button>
  );
}
