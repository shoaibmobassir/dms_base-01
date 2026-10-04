import type { Citation } from "@/api/types";
import { displayQuote } from "@/components/chat/CitationDocumentPanel";
import { FileText } from "lucide-react";
import { citationQuotes } from "@/components/chat/citationText";

export type ThreadDoc = { documentId: string; title: string; citations: Citation[] };

export function ThreadSources({ docs, onOpen }: { docs: ThreadDoc[]; onOpen: (c: Citation) => void }) {
  if (docs.length === 0) {
    return (
      <p className="p-4 text-sm text-muted-foreground" data-testid="thread-sources">
        No sources yet. Cited documents from this conversation appear here.
      </p>
    );
  }
  return (
    <div className="h-full space-y-3 overflow-y-auto p-3" data-testid="thread-sources">
      {docs.map((d) => (
        <div key={d.documentId} className="rounded-lg border border-border">
          <button
            type="button"
            onClick={() => onOpen(d.citations[0])}
            className="flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left hover:bg-secondary/50"
          >
            <FileText className="h-4 w-4 shrink-0 text-muted-foreground" />
            <span className="min-w-0 flex-1 truncate text-[13px] font-semibold text-ink">{d.title}</span>
            <span className="shrink-0 font-mono text-xs text-muted-foreground">
              {d.citations.length} {d.citations.length === 1 ? "citation" : "citations"}
            </span>
          </button>
          <div className="divide-y divide-border">
            {d.citations.map((c, i) => (
              <button
                key={i}
                type="button"
                onClick={() => onOpen(c)}
                className="block w-full px-3 py-2 text-left hover:bg-secondary/50"
              >
                <span className="line-clamp-2 text-[12px] italic text-muted-foreground">
                  {citationQuotes(c)[0] ? displayQuote(citationQuotes(c)[0]) : "Open the cited passage"}
                </span>
                {c.page != null && <span className="mt-0.5 block font-mono text-xs text-muted-foreground">p. {String(c.page)}</span>}
              </button>
            ))}
          </div>
        </div>
      ))}
    </div>
  );
}
