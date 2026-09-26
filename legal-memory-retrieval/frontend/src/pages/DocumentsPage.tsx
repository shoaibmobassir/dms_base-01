import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ingestDocument, PAGE_SIZE, useDocuments, useMatters } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, Icon, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { useDebounced } from "@/lib/use-debounced";

export function DocumentsPage() {
  const navigate = useNavigate();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [showUpload, setShowUpload] = useState(false);
  const q = useDebounced(query.trim());
  const documents = useDocuments({ q, page });

  useEffect(() => setPage(0), [q]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Documents"
        title="Documents are the firm's evidence."
        subtitle="Every document is connected to its matter, author and versions."
        actions={
          <Action onClick={() => setShowUpload(true)} icon="upload" testId="add-documents">
            Add document
          </Action>
        }
      />
      <SearchField value={query} onChange={setQuery} placeholder="Search title, author, id or full text…" testId="documents-search" />
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
                    </span>
                  ),
                },
                { key: "type", secondary: true, header: "Type", render: (doc) => <span className="text-sm text-muted-foreground">{doc.document_type}</span> },
                { key: "author", secondary: true, header: "Author", render: (doc) => <span className="text-sm text-muted-foreground">{doc.author_name || "—"}</span> },
                { key: "matter", secondary: true, header: "Matter", render: (doc) => <MonoId>{doc.matter_code || doc.matter_id || "—"}</MonoId> },
                { key: "date", header: "Date", align: "right", render: (doc) => doc.doc_date || "—" },
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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const options = matters.data?.items ?? [];
  const target = matterId || options[0]?.matter_id || "";

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const res = await ingestDocument({ title: title.trim(), matter_id: target, body: body.trim(), document_type: docType });
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
