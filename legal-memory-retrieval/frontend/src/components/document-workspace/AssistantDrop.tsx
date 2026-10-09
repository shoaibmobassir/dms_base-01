import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { FileText, GripVertical, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { attachmentKey, attachmentLabel, hasPageDrag, pageAttachment, readPageDrag, type PageDrag } from "@/lib/pageDrag";
import type { Attachment } from "@/api/types";
import { cn } from "@/lib/utils";

/**
 * The AI tab: drag a page (or part) from the reader or the page list onto it, say what to do, and continue in the
 * Assistant with that page attached. "Add this page" does the same without dragging.
 */
export function AssistantDrop({
  current,
  matterId,
  matterCode,
}: {
  /** The page being read, as it would be dragged. */
  current: PageDrag;
  matterId?: string | null;
  matterCode?: string | null;
}) {
  const navigate = useNavigate();
  const [pages, setPages] = useState<Attachment[]>([]);
  const [prompt, setPrompt] = useState("");
  const [over, setOver] = useState(false);

  const add = (p: PageDrag) =>
    setPages((list) => (list.some((a) => attachmentKey(a) === attachmentKey(pageAttachment(p))) ? list : [...list, pageAttachment(p)]));

  const send = () =>
    navigate(matterId ? `/chat?matter=${encodeURIComponent(matterId)}` : "/chat", {
      state: { handoff: { pages: pages.length ? pages : [pageAttachment(current)], prompt: prompt.trim() } },
    });

  return (
    <div className="space-y-3 text-sm" data-testid="assistant-drop">
      <div
        data-testid="assistant-dropzone"
        onDragOver={(e) => {
          if (!hasPageDrag(e)) return;
          e.preventDefault();
          e.dataTransfer.dropEffect = "copy";
          setOver(true);
        }}
        onDragLeave={() => setOver(false)}
        onDrop={(e) => {
          setOver(false);
          const p = readPageDrag(e);
          if (!p) return;
          e.preventDefault();
          add(p);
        }}
        className={cn(
          "rounded-lg border border-dashed px-3 py-4 text-center text-xs text-muted-foreground transition-colors",
          over ? "border-wine bg-wine-soft text-wine" : "border-border bg-secondary/30",
        )}
      >
        <GripVertical className="mx-auto mb-1 h-4 w-4" />
        Drag a page here to work on it with the Assistant
      </div>

      {pages.length > 0 && (
        <ul className="space-y-1" data-testid="assistant-pages">
          {pages.map((a) => (
            <li key={attachmentKey(a)} className="flex items-center gap-1.5 rounded-md border border-border bg-card px-2 py-1 text-xs">
              <FileText className="h-3.5 w-3.5 shrink-0 text-amber-500" />
              <span className="min-w-0 flex-1 truncate">{attachmentLabel(a)}</span>
              <button
                type="button"
                aria-label={`Remove ${attachmentLabel(a)}`}
                onClick={() => setPages((list) => list.filter((x) => attachmentKey(x) !== attachmentKey(a)))}
                className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}

      <Button type="button" variant="outline" size="sm" className="h-7 gap-1 text-xs" onClick={() => add(current)} data-testid="assistant-add-current">
        <Plus className="h-3 w-3" /> Add {current.unit} {current.number}
      </Button>

      <textarea
        value={prompt}
        onChange={(e) => setPrompt(e.target.value)}
        rows={3}
        placeholder="What should the Assistant do with it? (e.g. fix the numbering on this page)"
        aria-label="Instruction for the Assistant"
        data-testid="assistant-prompt"
        className="w-full resize-y rounded-md border border-border bg-background px-2 py-1.5 text-sm outline-none focus:ring-2 focus:ring-ring"
      />
      <div className="flex flex-wrap gap-2">
        <Button type="button" size="sm" onClick={send} data-testid="assistant-send">
          Continue in Assistant
        </Button>
        {matterCode && (
          <Button asChild variant="outline" size="sm">
            <Link to={`/ask?scope=${encodeURIComponent(matterCode)}&scopeType=matter`}>Ask the Firm</Link>
          </Button>
        )}
      </div>
    </div>
  );
}
