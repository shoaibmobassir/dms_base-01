import { useEffect, useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { BulkBar } from "@/components/common/BulkBar";
import { downloadDocument } from "@/api/resources";
import { useApp } from "@/context/AppContext";
import { PAGE_SIZE, useDocumentFacets, useDocuments } from "@/api/resources";
import type { DocumentItem } from "@/api/types";
import { DataTable, type TableSort } from "@/components/common/DataTable";
import { Action, EmptyState, Icon, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { MatterPicker } from "@/components/common/MatterPicker";
import { UploadFlow } from "@/components/documents/UploadFlow";
import { RecentUploads } from "@/components/documents/RecentUploads";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";
import { displayTitle, linkDocument, workspaceHref, type WorkspaceKind } from "@/api/workspaces";
import { TargetDialog, type TargetChoice } from "@/components/workbench/dialogs";
import { Link } from "react-router-dom";

type HomeFilter = "" | "matter" | "project" | "library" | "firm";
const HOMES: { key: HomeFilter; label: string }[] = [
  { key: "", label: "Everything" },
  { key: "matter", label: "Matters" },
  { key: "project", label: "Projects" },
  { key: "library", label: "Libraries" },
  { key: "firm", label: "Templates" },
];
const HOME_ICON: Record<WorkspaceKind, string> = { matter: "gavel", project: "folder_special", library: "person_book", firm: "library_books" };
import { useDebounced } from "@/lib/use-debounced";

/** "Uploaded" says where a file came from, not what it is: show the file kind instead. */
function documentKind(doc: { document_type: string; mime_type?: string | null; title: string }): string {
  if (doc.document_type && doc.document_type !== "Uploaded" && doc.document_type !== "Synced") return doc.document_type;
  const mime = doc.mime_type ?? "";
  const ext = doc.title.split(".").pop()?.toLowerCase() ?? "";
  if (mime.includes("pdf") || ext === "pdf") return "PDF";
  if (mime.includes("word") || ext === "docx" || ext === "doc") return "Word document";
  if (mime.includes("sheet") || ext === "xlsx") return "Spreadsheet";
  if (mime.startsWith("text/") || ext === "txt" || ext === "md") return "Text";
  return "File";
}

/** The Assistant with these documents attached (limited to their matter when they share one). */
function assistantLink(docs: DocumentItem[]) {
  const q = new URLSearchParams();
  for (const d of docs.slice(0, 10)) {
    q.append("doc", d.document_id);
    q.append("docTitle", d.title);
  }
  const matters = new Set(docs.map((d) => d.matter_id));
  if (matters.size === 1 && docs[0]?.matter_id) q.set("matter", docs[0].matter_id);
  return `/chat?${q.toString()}`;
}

export function DocumentsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [docType, setDocType] = useState("");
  const [matterId, setMatterId] = useState("");
  const [linking, setLinking] = useState(false);
  // "Add documents" in the command palette arrives as ?add=1.
  const [params, setParams] = useSearchParams();
  const [showUpload, setShowUpload] = useState(params.get("add") === "1");
  useEffect(() => {
    if (params.get("add") === "1")
      setParams((prev) => {
        const next = new URLSearchParams(prev);
        next.delete("add");
        return next;
      }, { replace: true });
  }, [params, setParams]);
  const { toast } = useApp();
  // Chosen rows, kept across pages (id to the row, so actions know titles and matters).
  const [chosen, setChosen] = useState<Map<string, DocumentItem>>(new Map());
  const [downloading, setDownloading] = useState(false);
  const q = useDebounced(query.trim());
  const sort: TableSort | undefined = params.get("sort")
    ? { key: params.get("sort")!, dir: params.get("dir") === "asc" ? "asc" : "desc" }
    : undefined;
  // Where a document lives is a filter in the address bar (shared links and reloads keep it).
  const home = (params.get("home") ?? "") as HomeFilter;
  const setHome = (h: HomeFilter) => setParams((prev) => {
    const next = new URLSearchParams(prev);
    if (h) next.set("home", h);
    else next.delete("home");
    return next;
  }, { replace: true });
  const documents = useDocuments({ q, page, sort, doc_type: docType || undefined, matter_id: matterId || undefined, homes: "all", home_kind: home || undefined });
  const facets = useDocumentFacets();

  useEffect(() => {
    setPage(0);
    setChosen(new Map());
  }, [q, docType, matterId, home]);
  useEffect(() => setPage(0), [params.get("sort"), params.get("dir")]);

  const selectClass = "rounded-md border border-border bg-card px-2.5 py-2 text-sm text-foreground focus:border-wine/50 focus:outline-none";

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Documents"
        count={documents.data ? `${documents.data.total} ${documents.data.total === 1 ? "document" : "documents"}` : undefined}
        subtitle="Every document you can open: matter files, your projects, your library and the firm's templates."
        actions={
          <>
            <Action to="/projects" icon="folder_special" testId="documents-projects">Projects</Action>
            <Action to="/work/library/me" icon="person_book" testId="documents-library">My library</Action>
            <Action onClick={() => setShowUpload(true)} icon="upload" testId="add-documents">
              Add to a matter
            </Action>
          </>
        }
      />
      <div className="flex flex-wrap gap-1 rounded-md border border-border p-0.5 text-sm sm:w-fit" role="radiogroup" aria-label="Where it lives" data-testid="documents-home">
        {HOMES.map((h) => (
          <button key={h.key} type="button" role="radio" aria-checked={home === h.key} onClick={() => setHome(h.key)}
            className={cn("rounded px-3 py-1", home === h.key ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}>
            {h.label}
          </button>
        ))}
      </div>
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchField value={query} onChange={setQuery} placeholder="Search title, author, id or full text…" testId="documents-search" />
        </div>
        <select value={docType} onChange={(e) => setDocType(e.target.value)} aria-label="Document type" data-testid="documents-type" className={selectClass}>
          <option value="">All types</option>
          {(facets.data?.document_types ?? []).map((t) => (
            <option key={t.value} value={t.value}>
              {t.value} ({t.n})
            </option>
          ))}
        </select>
        <div className="sm:w-64">
          <MatterPicker value={matterId || null} onChange={(m) => setMatterId(m?.matter_id ?? "")} allowNone noneLabel="All matters" testId="documents-matter" />
        </div>
        {(docType || matterId) && (
          <button type="button" onClick={() => { setDocType(""); setMatterId(""); }} className="text-xs font-medium text-wine hover:underline">
            Clear filters
          </button>
        )}
      </div>
      <BulkBar count={chosen.size} noun="document" onClear={() => setChosen(new Map())}>
        <Action
          to={assistantLink([...chosen.values()])}
          icon="edit_note"
          testId="bulk-assistant"
        >
          Work on in Assistant
        </Action>
        <Action icon="add_link" testId="bulk-link" onClick={() => setLinking(true)}>
          Add to project or library
        </Action>
        <Action
          icon="download"
          testId="bulk-download"
          onClick={() => {
            if (downloading) return;
            setDownloading(true);
            void (async () => {
              let failed = 0;
              for (const d of chosen.values()) {
                try {
                  await downloadDocument(d.document_id);
                } catch {
                  failed += 1;
                }
              }
              setDownloading(false);
              toast(failed ? `${failed} of ${chosen.size} could not be downloaded` : `${chosen.size} downloaded`);
            })();
          }}
        >
          {downloading ? "Downloading…" : "Download"}
        </Action>
      </BulkBar>
      <QueryState
        query={documents}
        isEmpty={(d) => d.items.length === 0}
        empty={<EmptyState title="No documents found" description="No documents match your search within your access scope." />}
      >
        {(d) => (
          <>
            <DataTable
              testId="documents-table"
              getRowKey={(doc) => doc.document_id}
              getRowHref={(doc) => `/documents/${doc.document_id}`}
              onRowClick={(doc) => navigate(`/documents/${doc.document_id}`)}
              rows={d.items}
              selection={{
                selected: new Set(chosen.keys()),
                label: (doc) => doc.title,
                onChange: (next) => {
                  const rows = new Map(d.items.map((x) => [x.document_id, x] as const));
                  setChosen((prev) => {
                    const out = new Map<string, DocumentItem>();
                    for (const id of next as Set<string>) {
                      const row = rows.get(id) ?? prev.get(id);
                      if (row) out.set(id, row);
                    }
                    return out;
                  });
                },
              }}
              sort={sort}
              onSort={(next) =>
                setParams((prev) => {
                  const out = new URLSearchParams(prev);
                  out.set("sort", next.key);
                  out.set("dir", next.dir);
                  return out;
                }, { replace: true })
              }
              columns={[
                {
                  key: "name",
                  header: "Name",
                  sortKey: "title",
                  render: (doc) => (
                    <span className="flex items-center gap-2">
                      <Icon name="description" className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
                      {displayTitle(doc.title)}
                      {doc.privacy && (
                        <Icon name={doc.privacy === "private" ? "lock" : "shield_lock"} className="text-warning-ink"
                          style={{ fontSize: 14 }} aria-label={doc.privacy === "private" ? "Private" : "Restricted"} data-testid="doc-privacy-icon" />
                      )}
                    </span>
                  ),
                },
                { key: "type", secondary: true, header: "Type", sortKey: "type", render: (doc) => <span className="text-sm text-muted-foreground">{documentKind(doc)}</span> },
                { key: "author", secondary: true, header: "Author", sortKey: "author", render: (doc) => <span className="text-sm text-muted-foreground">{doc.author_name || "—"}</span> },
                {
                  key: "matter",
                  secondary: true,
                  header: "Lives in",
                  sortKey: "matter",
                  render: (doc) => {
                    const kind = (doc.home_kind ?? "matter") as WorkspaceKind;
                    const label = kind === "matter" ? doc.matter_title : doc.home_label;
                    const to = kind === "matter" ? `/matters/${encodeURIComponent(doc.matter_id ?? "")}`
                      : kind === "library" && doc.home_label !== "My library" ? null
                      : workspaceHref(kind, kind === "library" ? "me" : kind === "firm" ? "templates" : doc.home_id ?? "");
                    return (
                      <div className="flex max-w-[280px] items-start gap-1.5">
                        <Icon name={HOME_ICON[kind]} className="mt-0.5 shrink-0 text-muted-foreground" style={{ fontSize: 14 }} />
                        <div className="min-w-0">
                          {to ? (
                            <Link to={to} onClick={(e) => e.stopPropagation()} className="block truncate text-sm hover:text-wine hover:underline">{label || "—"}</Link>
                          ) : <div className="truncate text-sm">{label || "—"}</div>}
                          {kind === "matter" && <MonoId>{doc.matter_code || doc.matter_id || ""}</MonoId>}
                        </div>
                      </div>
                    );
                  },
                },
                { key: "date", header: "Date", sortKey: "date", align: "right", render: (doc) => <span className="whitespace-nowrap tabular-nums">{formatDate(doc.doc_date)}</span> },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
      <RecentUploads />
      {showUpload && <UploadFlow onClose={() => setShowUpload(false)} />}
      <TargetDialog
        open={linking}
        onOpenChange={setLinking}
        title={`Show ${chosen.size} ${chosen.size === 1 ? "document" : "documents"} in a project or your library`}
        description="Nothing is copied: each stays one document with one history, and keeps the access of where it lives."
        confirm="Add"
        kinds={["project", "library", "matter"]}
        onConfirm={async (t: TargetChoice) => {
          let failed = 0;
          for (const d of chosen.values()) await linkDocument(d.document_id, t).catch(() => { failed += 1; });
          toast(failed ? `${chosen.size - failed} added; ${failed} already there or not allowed` : `${chosen.size} added`);
          setChosen(new Map());
        }}
      />
    </div>
  );
}
