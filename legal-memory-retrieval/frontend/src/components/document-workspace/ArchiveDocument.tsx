import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { archiveDocument, firmError } from "@/api/firm";
import { useDocumentPlaces } from "@/api/workspaces";
import { useMatter } from "@/api/resources";
import { Field, fieldControl } from "@/components/common/Field";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";

/** Archive a document (hide it for everyone; an administrator can restore it). Only for people who manage it. */
export function ArchiveDocument({ documentId, matterId, title }: { documentId: string; matterId?: string | null; title: string }) {
  // Matter documents: manage on the matter. Project, library and template documents: manage where they live.
  const matter = useMatter(matterId ?? "");
  const places = useDocumentPlaces(documentId, !matterId);
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const [open, setOpen] = useState(false);
  const [reason, setReason] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  if ((matterId ? matter.data?.my_level : places.data?.my_level) !== "manage") return null;

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await archiveDocument(documentId, reason);
      toast("Document archived");
      await queryClient.invalidateQueries();
      navigate("/documents");
    } catch (err) {
      setError(firmError(err));
      setBusy(false);
    }
  };

  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)} data-testid="document-archive">
        <Icon name="archive" style={{ fontSize: 16 }} /> Archive
      </Button>
      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-md" data-testid="archive-dialog">
          <DialogHeader>
            <DialogTitle>Archive “{title}”?</DialogTitle>
            <DialogDescription>It disappears from lists, search and answers for everyone. Nothing is deleted: an administrator can restore it.</DialogDescription>
          </DialogHeader>
          <Field label="Why is it being archived?" error={error}>
            {(p) => <textarea {...p} value={reason} onChange={(e) => setReason(e.target.value)} rows={3} maxLength={500} className={fieldControl} data-testid="archive-reason" />}
          </Field>
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
            <Button variant="destructive" disabled={busy || reason.trim().length < 3} onClick={submit} data-testid="archive-confirm">Archive document</Button>
          </div>
        </DialogContent>
      </Dialog>
    </>
  );
}
