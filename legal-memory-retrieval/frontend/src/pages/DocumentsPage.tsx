import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ingestDocument, PAGE_SIZE, useDocumentFacets, useDocuments, useMatters } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, Icon, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
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

export function DocumentsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [docType, setDocType] = useState("");
  const [matterId, setMatterId] = useState("");
  const [showUpload, setShowUpload] = useState(false);
  const q = useDebounced(query.trim());
  const documents = useDocuments({ q, page, doc_type: docType || undefined, matter_id: matterId || undefined });
  const facets = useDocumentFacets();
  const matters = useMatters({ limit: 200 });

  useEffect(() => setPage(0), [q, docType, matterId]);

  const selectClass = "rounded-md border border-border bg-card px-2.5 py-2 text-sm text-foreground focus:border-wine/50 focus:outline-hidden";

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Documents"
        count={documents.data ? `${documents.data.total} ${documents.data.total === 1 ? "document" : "documents"}` : undefined}
        subtitle="Every document is filed to its matter, with its author and versions."
        actions={
          <Action onClick={() => setShowUpload(true)} icon="upload" testId="add-documents">
            Add document
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
        <select value={matterId} onChange={(e) => setMatterId(e.target.value)} aria-label="Matter" data-testid="documents-matter" className={`${selectClass} max-w-[260px]`}>
          <option value="">All matters</option>
          {(matters.data?.items ?? []).map((m) => (
            <option key={m.matter_id} value={m.matter_id}>
              {m.matter_code} · {m.title}
            </option>
          ))}
        </select>
        {(docType || matterId) && (
          <button type="button" onClick={() => { setDocType(""); setMatterId(""); }} className="text-xs font-medium text-wine hover:underline">
            Clear filters
          </button>
        )}
      </div>
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
              onRowClick={(doc) => navigate(`/documents/${doc.document_id}`)}
              rows={d.items}
              columns={[
                {
                  key: "name",
                  header: "Name",
                  render: (doc) => (
                    <span className="flex items-center gap-2">
                      <Icon name="description" className="text-muted-foreground" style={{ fontSize: 16 }} />
                      {doc.title}
                      {doc.privacy && (
                        <Icon name={doc.privacy === "private" ? "lock" : "shield_lock"} className="text-amber-600"
                          style={{ fontSize: 14 }} aria-label={doc.privacy === "private" ? "Private" : "Restricted"} data-testid="doc-privacy-icon" />
                      )}
                    </span>
                  ),
                },
                { key: "type", secondary: true, header: "Type", render: (doc) => <span className="text-sm text-muted-foreground">{documentKind(doc)}</span> },
                { key: "author", secondary: true, header: "Author", render: (doc) => <span className="text-sm text-muted-foreground">{doc.author_name || "—"}</span> },
                {
                  key: "matter",
                  secondary: true,
                  header: "Matter",
                  render: (doc) => (
                    <div className="max-w-[280px]">
                      <div className="truncate text-sm">{doc.matter_title || "—"}</div>
                      <MonoId>{doc.matter_code || doc.matter_id || ""}</MonoId>
                    </div>
                  ),
                },
                { key: "date", header: "Date", align: "right", render: (doc) => <span className="whitespace-nowrap tabular-nums">{formatDate(doc.doc_date)}</span> },
              ]}
            />
            <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
          </>
        )}
      </QueryState>
      {showUpload && <UploadDialog onClose={() => setShowUpload(false)} />}
    </div>
  );
}

const DOC_TYPES = ["Memo", "Pleading", "Submission", "Correspondence", "Contract Draft", "Opinion"];

function UploadDialog({ onClose }: { onClose: () => void }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  // Only open matters the caller can see are valid targets.
  const matters = useMatters({ status: "Open", limit: 200 });
  const [title, setTitle] = useState("");
  const [matterId, setMatterId] = useState("");
  const [docType, setDocType] = useState(DOC_TYPES[0]);
  const [body, setBody] = useState("");
  const [privateDraft, setPrivateDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = matters.data?.items ?? [];
  const target = matterId || options[0]?.matter_id || "";

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await ingestDocument({ title: title.trim(), matter_id: target, body: body.trim(), document_type: docType,
        visibility: privateDraft ? "private" : "matter" });
      await queryClient.invalidateQueries();
      toast(`Indexed ${res.document_id ?? "document"}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Ingest failed");
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Add a document</DialogTitle>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <input
            className="w-full rounded-md border border-border bg-card px-3 py-2"
            placeholder="Title"
            aria-label="Title"
            value={title}
            onChange={(e) => setTitle(e.target.value)}
          />
          <select
            className="w-full rounded-md border border-border bg-card px-3 py-2"
            aria-label="Matter"
            value={target}
            onChange={(e) => setMatterId(e.target.value)}
            disabled={matters.isPending}
          >
            {options.map((m) => (
              <option key={m.matter_id} value={m.matter_id}>
                {m.matter_code} — {m.title}
              </option>
            ))}
          </select>
          <select
            className="w-full rounded-md border border-border bg-card px-3 py-2"
            aria-label="Document type"
            value={docType}
            onChange={(e) => setDocType(e.target.value)}
          >
            {DOC_TYPES.map((t) => (
              <option key={t}>{t}</option>
            ))}
          </select>
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={privateDraft} onChange={(e) => setPrivateDraft(e.target.checked)} data-testid="ingest-private" />
            Private draft — only I can see it until I share it
          </label>
          <textarea
            className="min-h-32 w-full rounded-md border border-border bg-card px-3 py-2"
            placeholder="Document text"
            aria-label="Document text"
            value={body}
            onChange={(e) => setBody(e.target.value)}
          />
          {error && <p className="text-destructive">{error}</p>}
          <p className="text-xs text-muted-foreground">The text is chunked and indexed into the matter, and inherits its permissions.</p>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button disabled={busy || !title.trim() || !target || !body.trim()} onClick={() => void submit()}>
            {busy ? "Indexing…" : "Ingest"}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
