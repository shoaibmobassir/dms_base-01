import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { copyContentFrom, editErrorMessage, getLockStatus, getPrivacy, listComments } from "@/api/editor";
import { useConfirm } from "@/components/common/Confirm";
import { keys } from "@/lib/keys";
import { useDirtyDocs } from "@/lib/dirtyDocs";
import { HistoryPanel } from "@/components/document-workspace/HistoryPanel";
import { useApp } from "@/context/AppContext";
import { useDocument } from "@/api/resources";
import { displayTitle, useDocumentPlaces, useWorkspaceItems, useWorkspaceSearch, type WorkspaceDocument, type WorkspaceKind } from "@/api/workspaces";
import { Icon } from "@/components/common/primitives";
import { Command, CommandEmpty, CommandGroup, CommandInput, CommandItem, CommandList } from "@/components/ui/command";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { useDebounced } from "@/lib/use-debounced";
import { iconFor, type OpenRequest } from "./Explorer";

/** Words inside this workspace's documents; a hit opens the document at the page where it matched. */
export function SearchView({ kind, id, onOpen }: { kind: WorkspaceKind; id: string; onOpen: (r: OpenRequest) => void }) {
  const [q, setQ] = useState("");
  const query = useDebounced(q, 300);
  const results = useWorkspaceSearch(kind, id, query);
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-search">
      <div className="border-b border-border px-3 py-2">
        <div className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Search this workspace</div>
        <input
          autoFocus
          value={q}
          onChange={(e) => setQ(e.target.value)}
          placeholder="Words in documents or titles"
          aria-label="Search this workspace"
          className="w-full rounded-md border border-border bg-card px-2.5 py-1.5 text-sm focus-visible:border-wine/60 focus-visible:outline-none"
          data-testid="workbench-search-input"
        />
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {query.trim().length < 2 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">Type at least 2 characters.</p>
        ) : results.isPending ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">Searching…</p>
        ) : results.isError ? (
          <p className="px-3 py-4 text-xs text-destructive">Search failed. Try again.</p>
        ) : results.data.length === 0 ? (
          <p className="px-3 py-4 text-xs text-muted-foreground">Nothing in this workspace matches “{query}”.</p>
        ) : (
          <ul className="divide-y divide-border">
            {results.data.map((h) => (
              <li key={h.document_id}>
                <button
                  type="button"
                  className="w-full px-3 py-2 text-left hover:bg-secondary/70"
                  onClick={() => {
                    const p = new URLSearchParams();
                    if (h.page_number) p.set("page", String(h.page_number));
                    if (h.chunk_id) p.set("chunk", h.chunk_id);
                    onOpen({ documentId: h.document_id, title: h.title, params: p.toString() });
                  }}
                  data-testid="workbench-search-hit"
                >
                  <div className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Icon name={iconFor({ title: h.title })} className="text-muted-foreground" style={{ fontSize: 15 }} />
                    <span className="truncate">{displayTitle(h.title)}</span>
                    {h.page_number ? <span className="ml-auto shrink-0 font-mono-id text-[11px] text-muted-foreground">p. {h.page_number}</span> : null}
                  </div>
                  {h.snippet && <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">{marked(h.snippet)}</p>}
                  {h.folder_path && <p className="mt-0.5 truncate text-[11px] text-muted-foreground/80">{h.folder_path}</p>}
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}

/** Render a server snippet whose matches are wrapped in {MARK_START}/{MARK_END}, without injecting HTML. */
function marked(snippet: string): ReactNode[] {
  return snippet.split(/(\{MARK_START\}.*?\{MARK_END\})/g).map((part, i) =>
    part.startsWith("{MARK_START}") ? (
      <mark key={i} className="rounded-sm bg-highlight px-0.5 text-foreground">
        {part.slice("{MARK_START}".length, -"{MARK_END}".length)}
      </mark>
    ) : (
      <span key={i}>{part}</span>
    ),
  );
}

/** ⌘P: find a document by name in this workspace, your library and the firm's templates (the server filters). */
export function QuickOpen({
  kind,
  id,
  open,
  onOpenChange,
  onOpen,
}: {
  kind: WorkspaceKind;
  id: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
  onOpen: (r: OpenRequest) => void;
}) {
  const [q, setQ] = useState("");
  const query = useDebounced(q, 150);
  const items = useWorkspaceItems(kind, id, { recursive: true, q: query, enabled: open });
  const library = useWorkspaceItems("library", "me", { recursive: true, q: query, enabled: open && kind !== "library" && query.length > 0 });
  const firm = useWorkspaceItems("firm", "templates", { recursive: true, q: query, enabled: open && kind !== "firm" && query.length > 0 });
  const docs = useMemo(
    () => (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted).slice(0, 100),
    [items.data],
  );
  const others = useMemo(() => {
    const seen = new Set(docs.map((d) => d.document_id));
    const pick = (list: typeof library.data, label: string) =>
      (list?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted && !seen.has(d.document_id)).slice(0, 20).map((d) => ({ d, label }));
    return [...pick(kind !== "library" ? library.data : undefined, "My library"), ...pick(kind !== "firm" ? firm.data : undefined, "Firm templates")];
  }, [docs, library.data, firm.data, kind]);
  // The server answers after each keystroke: highlight its best match, not an item from the previous list.
  const [highlight, setHighlight] = useState("");
  useEffect(() => {
    setHighlight(docs[0] ? `${docs[0].document_id}-${docs[0].folder}` : "");
  }, [docs]);
  const fresh = query === q && !items.isFetching;
  // Enter pressed while the list is still catching up opens the best match once it arrives.
  const [pendingEnter, setPendingEnter] = useState(false);
  useEffect(() => {
    if (!pendingEnter || !fresh) return;
    setPendingEnter(false);
    const first = docs[0];
    if (first) {
      onOpenChange(false);
      setQ("");
      onOpen({ documentId: first.document_id, title: first.title });
    }
  }, [pendingEnter, fresh, docs, onOpen, onOpenChange]);
  const choose = (d: WorkspaceDocument) => {
    onOpenChange(false);
    setQ("");
    onOpen({ documentId: d.document_id, title: d.title });
  };
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setQ(""); }}>
      <DialogContent className="max-w-xl overflow-hidden p-0" data-testid="quick-open">
        <DialogTitle className="sr-only">Open a document</DialogTitle>
        <Command shouldFilter={false} value={highlight} onValueChange={setHighlight}
          onKeyDown={(e) => { if (e.key === "Enter" && !fresh) { e.preventDefault(); setPendingEnter(true); } }}>
          <CommandInput placeholder="Open a document by name…" value={q} onValueChange={setQ} />
          <CommandList className="max-h-[50vh]">
            <CommandEmpty>{items.isFetching ? "Searching…" : "No document with that name."}</CommandEmpty>
            <CommandGroup heading={others.length ? "This workspace" : undefined}>
              {docs.map((d) => (
                <CommandItem key={`${d.document_id}-${d.folder}`} value={`${d.document_id}-${d.folder}`} onSelect={() => choose(d)}>
                  <Icon name={iconFor(d)} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
                  <span className="truncate">{displayTitle(d.title)}</span>
                  {d.folder && <span className="ml-auto truncate pl-3 text-xs text-muted-foreground">{d.folder}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
            {others.length > 0 && (
              <CommandGroup heading="Elsewhere">
                {others.map(({ d, label }) => (
                  <CommandItem key={`o-${d.document_id}`} value={`o-${d.document_id}`} onSelect={() => choose(d)}>
                    <Icon name={iconFor(d)} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
                    <span className="truncate">{displayTitle(d.title)}</span>
                    <span className="ml-auto truncate pl-3 text-xs text-muted-foreground">{label}</span>
                  </CommandItem>
                ))}
              </CommandGroup>
            )}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

export type WorkbenchCommand = { id: string; title: string; keys?: string; group: string; run: () => void; when?: boolean; /** A shortcut only, not listed. */ hidden?: boolean };

/** ⇧⌘P: every workbench action by name. */
export function WorkbenchCommands({
  open,
  onOpenChange,
  commands,
}: {
  open: boolean;
  onOpenChange: (o: boolean) => void;
  commands: WorkbenchCommand[];
}) {
  const groups = useMemo(() => {
    const out = new Map<string, WorkbenchCommand[]>();
    for (const c of commands.filter((c) => c.when !== false && !c.hidden)) out.set(c.group, [...(out.get(c.group) ?? []), c]);
    return [...out.entries()];
  }, [commands]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl overflow-hidden p-0" data-testid="workbench-commands">
        <DialogTitle className="sr-only">Commands</DialogTitle>
        <Command>
          <CommandInput placeholder="Type a command…" />
          <CommandList className="max-h-[50vh]">
            <CommandEmpty>No command matches.</CommandEmpty>
            {groups.map(([group, list]) => (
              <CommandGroup key={group} heading={group}>
                {list.map((c) => (
                  <CommandItem
                    key={c.id}
                    value={`${c.group} ${c.title}`}
                    onSelect={() => {
                      onOpenChange(false);
                      c.run();
                    }}
                    data-testid={`command-${c.id}`}
                  >
                    <span className="truncate">{c.title}</span>
                    {c.keys && <kbd className="ml-auto rounded border border-border px-1.5 font-mono-id text-[11px] text-muted-foreground">{keys(c.keys)}</kbd>}
                  </CommandItem>
                ))}
              </CommandGroup>
            ))}
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

const LEVEL_LABEL: Record<string, string> = { manage: "can manage", edit: "can edit", read: "read only" };

/** What the focused tab is: version, who is editing, unsaved edits, privacy, comments, where it lives, your access. */
export function StatusBar({ documentId, workspaceLabel, level, kind }: { documentId: string | null; workspaceLabel: string; level: string | undefined; kind: WorkspaceKind }) {
  const { identityKey, me } = useApp();
  const doc = useDocument(documentId ?? "", { lean: true });
  const places = useDocumentPlaces(documentId ?? "", !!documentId);
  const enabled = !!documentId && identityKey !== null;
  const lock = useQuery({ queryKey: [identityKey, "doc-lock", documentId], queryFn: () => getLockStatus(documentId!), enabled, refetchInterval: 30_000 });
  const privacy = useQuery({ queryKey: [identityKey, "doc-privacy", documentId], queryFn: () => getPrivacy(documentId!), enabled, retry: false });
  const comments = useQuery({ queryKey: [identityKey, "doc-comments-count", documentId], queryFn: () => listComments(documentId!), enabled, retry: false });
  const dirty = useDirtyDocs();
  const home = places.data?.places.find((p) => p.home);
  const links = (places.data?.places ?? []).filter((p) => !p.home).length;
  const d = documentId ? doc.data : undefined;
  const holder = lock.data?.lock;
  const openComments = (comments.data?.threads ?? []).filter((t) => t.status === "open").length;
  const pages = d?.current_version?.page_count ?? d?.page_count;
  return (
    <footer className="flex h-6 shrink-0 items-center gap-3 overflow-hidden border-t border-border bg-paper px-3 text-[11px] text-muted-foreground" data-testid="workbench-status">
      <span className="flex shrink-0 items-center gap-1 truncate">
        <Icon name="workspaces" style={{ fontSize: 13 }} /> {workspaceLabel}
        {level && <span className="ml-1">· {kind === "library" ? "yours" : LEVEL_LABEL[level] ?? level}</span>}
      </span>
      {d && (
        <>
          <span className="hidden truncate md:inline">{d.title}</span>
          {d.current_version?.version_number != null && <span className="font-mono-id">v{d.current_version.version_number}</span>}
          {pages ? <span className="hidden sm:inline">{pages} {pages === 1 ? "page" : "pages"}</span> : null}
          {documentId && dirty.has(documentId) && <span className="text-wine" data-testid="status-unsaved">● unsaved changes</span>}
          {holder && (
            <span className="flex items-center gap-1 text-warning-ink" data-testid="status-lock">
              <Icon name="edit" style={{ fontSize: 13 }} /> {holder.member_id === me?.member_id ? "You are editing" : `${holder.name} is editing`}
            </span>
          )}
          {privacy.data && privacy.data.visibility !== "matter" && (
            <span className="flex items-center gap-1" title={privacy.data.visibility === "private" ? "Private: only its owner and people it is shared with" : "Restricted"}>
              <Icon name="lock" style={{ fontSize: 13 }} /> {privacy.data.visibility === "private" ? "Private" : "Restricted"}
            </span>
          )}
          {openComments > 0 && (
            <span className="flex items-center gap-1"><Icon name="chat_bubble" style={{ fontSize: 13 }} /> {openComments}</span>
          )}
          {home && !home.hidden && (
            <span className="hidden items-center gap-1 truncate lg:flex" title="Where the document lives">
              <Icon name={home.kind === "matter" ? "gavel" : home.kind === "project" ? "folder_special" : home.kind === "firm" ? "library_books" : "person_book"} style={{ fontSize: 13 }} />
              {home.label}
            </span>
          )}
          {links > 0 && (
            <span className="hidden items-center gap-1 lg:flex" title="Also shown in other workspaces">
              <Icon name="link" style={{ fontSize: 13 }} /> {links}
            </span>
          )}
          {places.data?.tags.user.map((t) => <span key={t} className="hidden lg:inline">#{t}</span>)}
        </>
      )}
      <span className="ml-auto hidden shrink-0 xl:inline">{keys("⌘P")} open · {keys("⇧⌘P")} commands</span>
    </footer>
  );
}

/** The active document's history (versions as commits), and replacing its content with another document's. */
export function ChangesView({
  kind,
  id,
  documentId,
  title,
  canEdit,
  onOpenVersion,
}: {
  kind: WorkspaceKind;
  id: string;
  documentId: string | null;
  title?: string;
  canEdit: boolean;
  onOpenVersion: (versionId: string) => void;
}) {
  const [replacing, setReplacing] = useState(false);
  if (!documentId) {
    return (
      <div className="px-3 py-4 text-xs text-muted-foreground" data-testid="workbench-changes">
        Open a document to see its versions: who changed what, compare any two, restore one.
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-changes">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Versions · {title ?? documentId}
        </div>
        {canEdit && <button
          type="button"
          className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={() => setReplacing(true)}
          title="Make another document's content this document's next version"
          data-testid="changes-replace-from"
        >
          Replace from…
        </button>}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto p-3">
        <HistoryPanel documentId={documentId} onOpen={onOpenVersion} />
      </div>
      <ReplaceFromDialog kind={kind} id={id} documentId={documentId} open={replacing} onOpenChange={setReplacing} />
    </div>
  );
}

function ReplaceFromDialog({
  kind,
  id,
  documentId,
  open,
  onOpenChange,
}: {
  kind: WorkspaceKind;
  id: string;
  documentId: string;
  open: boolean;
  onOpenChange: (o: boolean) => void;
}) {
  const items = useWorkspaceItems(kind, id, { recursive: true, enabled: open });
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const confirm = useConfirm();
  const docs = (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted && d.document_id !== documentId);
  const replace = async (source: WorkspaceDocument) => {
    const ok = await confirm({
      title: `Replace this document's content with “${source.title}”?`,
      description: `It gets a new version with the content of “${source.title}”, which is not changed. The earlier versions stay in History and can be restored.`,
      confirmLabel: "Replace content",
    });
    if (!ok) return;
    try {
      const out = await copyContentFrom(documentId, { source_document_id: source.document_id });
      await queryClient.invalidateQueries({ predicate: (q) => JSON.stringify(q.queryKey).includes(documentId) });
      toast(`Version ${out.version_number} now has the content of ${out.source.title}. ${out.source.note}`);
      onOpenChange(false);
    } catch (err) {
      toast(editErrorMessage(err));
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl overflow-hidden p-0" data-testid="replace-from-dialog">
        <DialogTitle className="px-4 pt-4 text-base">Replace content from another document</DialogTitle>
        <p className="px-4 text-xs text-muted-foreground">
          The chosen document's current content becomes this document's next version. The chosen document is not changed and keeps
          its own history; this one's earlier versions stay in its history.
        </p>
        <Command>
          <CommandInput placeholder="Choose a document in this workspace…" />
          <CommandList className="max-h-[45vh]">
            <CommandEmpty>{items.isPending ? "Loading…" : "No other document here."}</CommandEmpty>
            <CommandGroup>
              {docs.map((d) => (
                <CommandItem key={d.document_id} value={`${d.title} ${d.document_id}`} onSelect={() => void replace(d)}>
                  <Icon name={iconFor(d)} className="text-muted-foreground" style={{ fontSize: 16 }} />
                  <span className="truncate">{displayTitle(d.title)}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
