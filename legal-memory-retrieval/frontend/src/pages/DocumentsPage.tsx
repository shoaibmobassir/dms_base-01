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
  const documents = useDocuments({ q, page, sort, doc_type: docType || undefined, matter_id: matterId || undefined });
  const facets = useDocumentFacets();

  useEffect(() => {
    setPage(0);
    setChosen(new Map());
  }, [q, docType, matterId]);
  useEffect(() => setPage(0), [params.get("sort"), params.get("dir")]);

  const selectClass = "rounded-md border border-border bg-card px-2.5 py-2 text-sm text-foreground focus:border-wine/50 focus:outline-none";

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Documents"
        count={documents.data ? `${documents.data.total} ${documents.data.total === 1 ? "document" : "documents"}` : undefined}
        subtitle="Every document is filed to its matter, with its author and versions."
        actions={
          <Action onClick={() => setShowUpload(true)} icon="upload" testId="add-documents">
            Add documents
          </Action>
        }
      />
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
                      <Icon name="description" className="text-muted-foreground" style={{ fontSize: 16 }} />
                      {doc.title}
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
                  header: "Matter",
                  sortKey: "matter",
                  render: (doc) => (
                    <div className="max-w-[280px]">
                      <div className="truncate text-sm">{doc.matter_title || "—"}</div>
                      <MonoId>{doc.matter_code || doc.matter_id || ""}</MonoId>
                    </div>
                  ),
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
    </div>
  );
}
