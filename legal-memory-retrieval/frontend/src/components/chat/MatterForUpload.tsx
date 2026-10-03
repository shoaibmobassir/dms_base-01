import { useState } from "react";
import { type MatterOption, MatterPicker } from "@/components/common/MatterPicker";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

export function MatterForUpload({ onChoose }: { onChoose: (m: MatterOption | null) => void }) {
  const [matter, setMatter] = useState<MatterOption | null>(null);
  return (
    <Dialog open onOpenChange={(v) => !v && onChoose(null)}>
      <DialogContent className="max-w-md" data-testid="upload-matter-prompt">
        <DialogHeader>
          <DialogTitle className="font-display text-xl">Which matter is this document for?</DialogTitle>
          <DialogDescription>It is filed to that matter and follows its access rules.</DialogDescription>
        </DialogHeader>
        <MatterPicker value={matter?.matter_id ?? null} onChange={setMatter} status="Open" testId="chat-upload-matter" />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={() => onChoose(null)} className="rounded-md border border-border px-3 py-1.5 text-sm hover:bg-secondary">
            Cancel
          </button>
          <button
            type="button"
            disabled={!matter}
            onClick={() => onChoose(matter)}
            data-testid="chat-upload-matter-confirm"
            className="rounded-md bg-primary px-3 py-1.5 text-sm font-semibold text-primary-foreground disabled:opacity-50"
          >
            File and attach
          </button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
