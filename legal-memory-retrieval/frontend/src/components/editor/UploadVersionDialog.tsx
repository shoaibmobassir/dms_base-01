import { useState } from "react";
import { editErrorMessage, uploadVersion } from "@/api/editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";

/** Upload a file as the document's next version (attributed to the signed-in person). */
export function UploadVersionDialog({
  documentId,
  baseVersionId,
  versionNumber,
  open,
  onOpenChange,
  onUploaded,
}: {
  documentId: string;
  baseVersionId?: string | null;
  versionNumber?: number | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onUploaded: (v: { version_id: string; version_number: number }) => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [note, setNote] = useState("");
  const [label, setLabel] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const v = await uploadVersion(documentId, file, { baseVersionId: baseVersionId ?? undefined, note, label: label || undefined });
      setFile(null);
      setNote("");
      setLabel("");
      onUploaded(v);
      onOpenChange(false);
    } catch (err) {
      setError(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="upload-version-dialog">
        <DialogHeader>
          <DialogTitle>Upload a new version</DialogTitle>
          <DialogDescription>
            {versionNumber ? `The file becomes v${versionNumber + 1}, based on v${versionNumber}.` : "The file becomes the next version."} It is
            recorded under your name.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <input
            type="file"
            accept=".docx,.pdf,.txt,.md"
            onChange={(e) => setFile(e.target.files?.[0] ?? null)}
            className="block w-full text-sm"
            data-testid="upload-version-file"
          />
          <Input placeholder="What changed and why (e.g. counterparty mark-up)" value={note} onChange={(e) => setNote(e.target.value)} />
          <Input placeholder="Label (optional, e.g. Execution version)" value={label} onChange={(e) => setLabel(e.target.value)} />
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={!file || busy} onClick={() => void submit()} data-testid="upload-version-submit">
              {busy ? "Uploading…" : "Upload version"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
