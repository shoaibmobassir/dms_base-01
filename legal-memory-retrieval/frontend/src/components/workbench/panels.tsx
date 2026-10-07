import { useEffect, useMemo, useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { copyContentFrom, editErrorMessage } from "@/api/editor";
import { HistoryPanel } from "@/components/document-workspace/HistoryPanel";
import { useApp } from "@/context/AppContext";
import { useDocument } from "@/api/resources";
import { useDocumentPlaces, useWorkspaceItems, useWorkspaceSearch, type WorkspaceDocument, type WorkspaceKind } from "@/api/workspaces";
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
                    <span className="truncate">{h.title}</span>
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

/** ⌘P: find a document of this workspace by name (the server filters, so it works at any size). */
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
  const docs = useMemo(
    () => (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted).slice(0, 100),
    [items.data],
  );
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
  return (
    <Dialog open={open} onOpenChange={(o) => { onOpenChange(o); if (!o) setQ(""); }}>
      <DialogContent className="max-w-xl overflow-hidden p-0" data-testid="quick-open">
        <DialogTitle className="sr-only">Open a document</DialogTitle>
        <Command shouldFilter={false} value={highlight} onValueChange={setHighlight}
          onKeyDown={(e) => { if (e.key === "Enter" && !fresh) { e.preventDefault(); setPendingEnter(true); } }}>
          <CommandInput placeholder="Open a document by name…" value={q} onValueChange={setQ} />
          <CommandList className="max-h-[50vh]">
            <CommandEmpty>{items.isFetching ? "Searching…" : "No document with that name."}</CommandEmpty>
            <CommandGroup>
              {docs.map((d) => (
                <CommandItem
                  key={`${d.document_id}-${d.folder}`}
                  value={`${d.document_id}-${d.folder}`}
                  onSelect={() => {
                    onOpenChange(false);
                    setQ("");
                    onOpen({ documentId: d.document_id, title: d.title });
                  }}
                >
                  <Icon name={iconFor(d)} className="text-muted-foreground" style={{ fontSize: 16 }} />
                  <span className="truncate">{d.title}</span>
                  {d.folder && <span className="ml-auto truncate pl-3 text-xs text-muted-foreground">{d.folder}</span>}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

export type WorkbenchCommand = { id: string; title: string; keys?: string; group: string; run: () => void; when?: boolean };

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
    for (const c of commands.filter((c) => c.when !== false)) out.set(c.group, [...(out.get(c.group) ?? []), c]);
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
                    {c.keys && <kbd className="ml-auto rounded border border-border px-1.5 font-mono-id text-[11px] text-muted-foreground">{c.keys}</kbd>}
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

/** What the focused tab is: version, where it lives, tags, your access. */
export function StatusBar({ documentId, workspaceLabel, level }: { documentId: string | null; workspaceLabel: string; level: string | undefined }) {
  const doc = useDocument(documentId ?? "", { lean: true });
  const places = useDocumentPlaces(documentId ?? "", !!documentId);
  const home = places.data?.places.find((p) => p.home);
  const links = (places.data?.places ?? []).filter((p) => !p.home).length;
  const d = documentId ? doc.data : undefined;
  return (
    <footer className="flex h-6 shrink-0 items-center gap-3 border-t border-border bg-paper px-3 text-[11px] text-muted-foreground" data-testid="workbench-status">
      <span className="flex items-center gap-1 truncate">
        <Icon name="workspaces" style={{ fontSize: 13 }} /> {workspaceLabel}
        {level && <span className="ml-1">· {level === "manage" ? "owner" : level === "edit" ? "can edit" : "read only"}</span>}
      </span>
      {d && (
        <>
          <span className="truncate">{d.title}</span>
          {d.current_version?.version_number != null && <span className="font-mono-id">v{d.current_version.version_number}</span>}
          {home && !home.hidden && (
            <span className="flex items-center gap-1 truncate" title="Where the document lives">
              <Icon name={home.kind === "matter" ? "gavel" : home.kind === "project" ? "folder_special" : "person"} style={{ fontSize: 13 }} />
              {home.label}
            </span>
          )}
          {links > 0 && (
            <span className="flex items-center gap-1" title="Also shown in other workspaces">
              <Icon name="link" style={{ fontSize: 13 }} /> {links}
            </span>
          )}
          {places.data?.tags.user.map((t) => <span key={t}>#{t}</span>)}
        </>
      )}
      <span className="ml-auto hidden sm:inline">⌘P open · ⇧⌘P commands · ⌘\\ split</span>
    </footer>
  );
}

/** The active document's history (versions as commits), and replacing its content with another document's. */
export function ChangesView({
  kind,
  id,
  documentId,
  title,
  onOpenVersion,
}: {
  kind: WorkspaceKind;
  id: string;
  documentId: string | null;
  title?: string;
  onOpenVersion: (versionId: string) => void;
}) {
  const [replacing, setReplacing] = useState(false);
  if (!documentId) {
    return (
      <div className="px-3 py-4 text-xs text-muted-foreground" data-testid="workbench-changes">
        Open a document to see its versions: who changed what, compare any two, restore or delete one.
      </div>
    );
  }
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-changes">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1 truncate text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">
          Changes · {title ?? documentId}
        </div>
        <button
          type="button"
          className="rounded px-1.5 py-0.5 text-[11px] text-muted-foreground hover:bg-secondary hover:text-foreground"
          onClick={() => setReplacing(true)}
          title="Make another document's content this document's next version"
          data-testid="changes-replace-from"
        >
          Replace from…
        </button>
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
  const docs = (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted && d.document_id !== documentId);
  const replace = async (source: WorkspaceDocument) => {
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
                  <span className="truncate">{d.title}</span>
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </DialogContent>
    </Dialog>
  );
}
