import { useRef, useState, type DragEvent } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { ingestDocument } from "@/api/resources";
import { ACCEPTED_TYPES, fileProblem, pathOf, uploadToMatter, type UploadOutcome } from "@/api/uploads";
import { MatterPicker, type MatterOption } from "@/components/common/MatterPicker";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const DOC_TYPES = ["Memo", "Pleading", "Submission", "Correspondence", "Contract Draft", "Opinion"];
const fieldCls = "w-full rounded-md border border-border bg-card px-3 py-2 text-sm";

function size(bytes: number) {
  return bytes < 1024 * 1024 ? `${Math.max(1, Math.round(bytes / 1024))} KB` : `${(bytes / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Adds documents to the firm. The matter is always chosen by the person (or fixed by the
 * page they came from): a document is never filed into a matter by default.
 */
export function UploadFlow({ onClose, matter: fixed }: { onClose: () => void; matter?: MatterOption | null }) {
  const [mode, setMode] = useState<"files" | "text">("files");
  const [matter, setMatter] = useState<MatterOption | null>(fixed ?? null);

  return (
    <Dialog open onOpenChange={(v) => !v && onClose()}>
      <DialogContent className="max-w-xl" data-testid="upload-flow">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Add documents</DialogTitle>
          <DialogDescription>Documents are filed to one matter and follow its access rules.</DialogDescription>
        </DialogHeader>

        {fixed ? (
          <p className="text-sm">
            Filing to <span className="font-medium">{fixed.matter_code}</span> · {fixed.title}
          </p>
        ) : (
          <MatterPicker value={matter?.matter_id ?? null} onChange={setMatter} label="Matter (required)" status="Open" testId="upload-matter" />
        )}

        <div className="flex gap-1 border-b border-border" role="tablist">
          {(
            [
              ["files", "Upload files"],
              ["text", "Paste text"],
            ] as const
          ).map(([key, label]) => (
            <button
              key={key}
              type="button"
              role="tab"
              aria-selected={mode === key}
              onClick={() => setMode(key)}
              className={cn("relative px-3 py-2 text-sm", mode === key ? "font-semibold text-wine" : "text-muted-foreground hover:text-foreground")}
            >
              {label}
              {mode === key && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-wine" />}
            </button>
          ))}
        </div>

        {mode === "files" ? <FilesTab matter={matter} onClose={onClose} /> : <TextTab matter={matter} onClose={onClose} />}
      </DialogContent>
    </Dialog>
  );
}

function FilesTab({ matter, onClose }: { matter: MatterOption | null; onClose: () => void }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const input = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const abort = useRef<AbortController | null>(null);
  const [files, setFiles] = useState<File[]>([]);
  const [over, setOver] = useState(false);
  const [busy, setBusy] = useState(false);
  const [progress, setProgress] = useState<[number, number] | null>(null);
  const [outcomes, setOutcomes] = useState<UploadOutcome[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  const add = (list: FileList | File[]) => {
    const next = [...files];
    for (const f of Array.from(list)) if (!next.some((x) => pathOf(x) === pathOf(f) && x.size === f.size)) next.push(f);
    setFiles(next);
    setOutcomes(null);
  };
  const onDrop = (e: DragEvent) => {
    e.preventDefault();
    setOver(false);
    if (e.dataTransfer.files.length) add(e.dataTransfer.files);
  };

  const valid = files.filter((f) => !fileProblem(f));
  const submit = async () => {
    if (!matter || valid.length === 0) return;
    setBusy(true);
    setError(null);
    setProgress([0, valid.length]);
    abort.current = new AbortController();
    try {
      const result = await uploadToMatter(matter.matter_id, valid, {
        signal: abort.current.signal,
        onProgress: (done, total) => setProgress([done, total]),
      });
      setOutcomes(result);
      await queryClient.invalidateQueries();
      const ok = result.filter((r) => r.status === "indexed").length;
      toast(ok === result.length ? `${ok} ${ok === 1 ? "document" : "documents"} added to ${matter.matter_code}` : `${ok} of ${result.length} added to ${matter.matter_code}`);
    } catch (err) {
      if ((err as { name?: string }).name === "AbortError") setError("Upload cancelled. Files already received may still be processed.");
      else setError(err instanceof Error ? err.message : "Upload failed");
    } finally {
      setBusy(false);
      setProgress(null);
      abort.current = null;
    }
  };

  if (outcomes) {
    return (
      <div className="space-y-3" data-testid="upload-results">
        <ul className="divide-y divide-border rounded-md border border-border">
          {outcomes.map((o) => (
            <li key={pathOf(o.file)} className="flex items-center gap-2 px-3 py-2 text-sm">
              <Icon
                name={o.status === "failed" ? "error" : o.status === "duplicate" ? "content_copy" : "check_circle"}
                className={o.status === "failed" ? "text-destructive" : o.status === "duplicate" ? "text-muted-foreground" : "text-success"}
                style={{ fontSize: 18 }}
              />
              <span className="min-w-0 flex-1">
                <span className="block truncate">{pathOf(o.file)}</span>
                <span className="block text-xs text-muted-foreground">
                  {o.status === "indexed" ? "Added and indexed" : o.status === "duplicate" ? "Already in the firm's records" : o.error}
                </span>
              </span>
              {o.documentId && o.status !== "failed" && (
                <Link to={`/documents/${o.documentId}`} onClick={onClose} className="shrink-0 text-xs font-semibold text-wine hover:underline">
                  Open
                </Link>
              )}
            </li>
          ))}
        </ul>
        <div className="flex justify-end">
          <Button onClick={onClose}>Done</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div
        onDragOver={(e) => {
          e.preventDefault();
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={onDrop}
        className={cn("flex flex-col items-center gap-2 rounded-lg border border-dashed px-6 py-8 text-center", over ? "border-wine bg-wine-soft/40" : "border-border")}
        data-testid="upload-dropzone"
      >
        <Icon name="upload_file" className="text-muted-foreground" style={{ fontSize: 30 }} />
        <p className="text-sm">Drop files here, or</p>
        <div className="flex gap-2">
          <Button type="button" variant="outline" size="sm" onClick={() => input.current?.click()} disabled={busy}>
            Choose files
          </Button>
          <Button type="button" variant="outline" size="sm" onClick={() => folderInput.current?.click()} disabled={busy} data-testid="upload-choose-folder">
            Choose a folder
          </Button>
        </div>
        <input
          ref={folderInput}
          type="file"
          // @ts-expect-error webkitdirectory is supported by every current browser but is not in the DOM typings
          webkitdirectory=""
          className="hidden"
          data-testid="upload-folder-input"
          onChange={(e) => {
            if (e.target.files) add(e.target.files);
            e.target.value = "";
          }}
        />
        <p className="text-xs text-muted-foreground">PDF, Word (.docx) or text, up to 50 MB each. A folder keeps its folder names.</p>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPTED_TYPES}
          className="hidden"
          data-testid="upload-input"
          onChange={(e) => {
            if (e.target.files) add(e.target.files);
            e.target.value = "";
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="max-h-48 divide-y divide-border overflow-y-auto rounded-md border border-border" data-testid="upload-files">
          {files.map((f) => {
            const problem = fileProblem(f);
            return (
              <li key={`${pathOf(f)}-${f.size}`} className="flex items-center gap-2 px-3 py-2 text-sm">
                <Icon name={problem ? "error" : "description"} className={problem ? "text-destructive" : "text-muted-foreground"} style={{ fontSize: 18 }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{pathOf(f)}</span>
                  <span className={cn("block text-xs", problem ? "text-destructive" : "text-muted-foreground")}>{problem ?? size(f.size)}</span>
                </span>
                {!busy && (
                  <button type="button" aria-label={`Remove ${pathOf(f)}`} onClick={() => setFiles(files.filter((x) => x !== f))} className="rounded p-1.5 text-muted-foreground hover:bg-secondary">
                    <Icon name="close" style={{ fontSize: 16 }} />
                  </button>
                )}
              </li>
            );
          })}
        </ul>
      )}

      {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      {!matter && files.length > 0 && <p className="text-xs text-muted-foreground">Choose the matter these documents belong to.</p>}

      <div className="flex items-center justify-end gap-2">
        {progress && (
          <span className="mr-auto text-xs text-muted-foreground" role="status">
            Indexing {progress[0]} of {progress[1]}…
          </span>
        )}
        {busy ? (
          <Button variant="outline" onClick={() => abort.current?.abort()}>
            Stop waiting
          </Button>
        ) : (
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
        )}
        <Button disabled={busy || !matter || valid.length === 0} onClick={() => void submit()} data-testid="upload-submit">
          {busy ? "Uploading…" : `Add ${valid.length || ""} ${valid.length === 1 ? "document" : "documents"}`.replace("  ", " ")}
        </Button>
      </div>
    </div>
  );
}

function TextTab({ matter, onClose }: { matter: MatterOption | null; onClose: () => void }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [docType, setDocType] = useState(DOC_TYPES[0]);
  const [body, setBody] = useState("");
  const [priv, setPriv] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!matter) return;
    setBusy(true);
    setError(null);
    try {
      const res = await ingestDocument({ title: title.trim(), matter_id: matter.matter_id, body: body.trim(), document_type: docType, visibility: priv ? "private" : "matter" });
      await queryClient.invalidateQueries();
      toast(`Added ${res.document_id ?? "document"} to ${matter.matter_code}`);
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "The document was not added");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-3 text-sm">
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Title</span>
        <input className={fieldCls} value={title} onChange={(e) => setTitle(e.target.value)} data-testid="upload-text-title" />
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Document type</span>
        <select className={fieldCls} value={docType} onChange={(e) => setDocType(e.target.value)}>
          {DOC_TYPES.map((t) => (
            <option key={t}>{t}</option>
          ))}
        </select>
      </label>
      <label className="block">
        <span className="mb-1 block text-xs font-medium text-muted-foreground">Text</span>
        <textarea className={`${fieldCls} min-h-32`} value={body} onChange={(e) => setBody(e.target.value)} data-testid="upload-text-body" />
      </label>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={priv} onChange={(e) => setPriv(e.target.checked)} data-testid="ingest-private" />
        Private draft: only I can see it until I share it
      </label>
      {error && <p className="text-destructive" role="alert">{error}</p>}
      <div className="flex justify-end gap-2">
        <Button variant="outline" onClick={onClose}>Cancel</Button>
        <Button disabled={busy || !matter || !title.trim() || !body.trim()} onClick={() => void submit()} data-testid="upload-text-submit">
          {busy ? "Indexing…" : "Add document"}
        </Button>
      </div>
    </div>
  );
}
