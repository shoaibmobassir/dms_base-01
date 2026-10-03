import { Suspense, lazy, useState } from "react";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/common/primitives";
import { cn } from "@/lib/utils";
import { CommentsPanel, SelectionComment, useDocComments } from "@/components/comments/DocComments";
import { ReviewPanel } from "@/components/editor/ReviewPanel";

const DocumentViewer = lazy(() => import("@/components/viewer/DocumentViewer").then((m) => ({ default: m.DocumentViewer })));

/** What the sidebar shows: the comment threads, or Word's reviewing pane. */
export type ExactSide = { kind: "comments" } | {
  kind: "review";
  baseVersionId: string;
  canWrite: boolean;
  onNewVersion: (versionNumber: number, note: string) => void;
};

/**
 * The document exactly as filed (rendered pages) with comments: select text on a page to
 * comment on it; threads are listed beside the pages. The document page uses the same comments.
 */
export function ExactView({ documentId, currentVersionId, side = { kind: "comments" }, showViews = false }: {
  documentId: string;
  currentVersionId: string;
  side?: ExactSide;
  /** Offer Markup / Final / Original (Word files with tracked changes). */
  showViews?: boolean;
}) {
  const [renderView, setRenderView] = useState<"markup" | "final" | "original">("markup");
  // null = the current version; otherwise an earlier version opened from a detached thread.
  const [viewing, setViewing] = useState<{ versionId: string; number: number | null } | null>(null);
  // Comments are placed on the pages as filed; the Final / Original renditions lay out differently.
  const readOnlyVersion = Boolean(viewing) || renderView !== "markup";
  const dc = useDocComments({ documentId, versionId: viewing?.versionId, canAdd: !readOnlyVersion });
  const { marks } = dc;

  return (
    <div className="grid flex-1 gap-6 px-6 py-6 xl:grid-cols-[minmax(0,1fr)_340px]">
      {viewing && (
        <div className="flex items-center gap-3 rounded-md border border-warning/60 bg-warning-soft px-3 py-2 text-sm xl:col-span-2" data-testid="exact-old-version">
          <Icon name="history" style={{ fontSize: 16 }} />
          Viewing v{viewing.number ?? "?"}, an earlier version, as it was when the comment was made.
          <Button size="sm" variant="outline" className="ml-auto" onClick={() => { setViewing(null); dc.setLocated({}); }}>
            Back to the current version
          </Button>
        </div>
      )}
      {/* contain: fit-width pages must not widen the layout that sizes them */}
      <div className="flex h-[calc(100dvh-14rem)] min-w-0 flex-col overflow-hidden rounded-md border border-border bg-card [contain:inline-size]" data-testid="editor-exact">
        {showViews && (
          <div className="flex items-center gap-1 border-b border-border px-2 py-1 text-xs" role="tablist" aria-label="Show">
            {([["markup", "All markup"], ["final", "Final"], ["original", "Original"]] as const).map(([k, label]) => (
              <button key={k} type="button" role="tab" aria-selected={renderView === k} onClick={() => setRenderView(k)} data-testid={`exact-view-${k}`}
                className={cn("rounded px-2 py-0.5", renderView === k ? "bg-secondary font-medium text-foreground" : "text-muted-foreground hover:bg-secondary")}>
                {label}
              </button>
            ))}
            <span className="ml-2 text-muted-foreground">
              {renderView === "markup" ? "As filed, with tracked changes" : renderView === "final" ? "Every change accepted" : "Every change rejected"}
            </span>
          </div>
        )}
        <div className="min-h-0 flex-1">
          <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading pages…</p>}>
            <DocumentViewer
              key={`${viewing?.versionId ?? currentVersionId}-${renderView}`}
              src={`/api/documents/${encodeURIComponent(documentId)}/render?version_id=${encodeURIComponent(viewing?.versionId ?? currentVersionId)}${renderView !== "markup" ? `&view=${renderView}` : ""}`}
              target={dc.target}
              marks={marks}
              onMarkClick={(cid) => {
                dc.setActive(cid);
                document.getElementById(`comment-${cid}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
              }}
              onMarksLocated={dc.setLocated}
              onSelectText={dc.onSelectText}
            />
          </Suspense>
        </div>
      </div>

      {side.kind === "review" ? (
        <aside className="flex max-h-[calc(100dvh-14rem)] min-h-0 flex-col">
          <ReviewPanel documentId={documentId} baseVersionId={side.baseVersionId} canWrite={side.canWrite}
            onNewVersion={side.onNewVersion} onJump={(quote) => dc.setTarget({ page: null, quote, nonce: Date.now() })} />
        </aside>
      ) : (
        <aside className="flex max-h-[calc(100dvh-14rem)] min-h-0 flex-col rounded-lg border border-border bg-card">
          <CommentsPanel
            dc={dc}
            onViewVersion={(versionId, number) => setViewing({ versionId, number })}
            note={viewing ? "Comments are added on the current version." : "Switch to All markup to add comments."}
          />
        </aside>
      )}
      <SelectionComment dc={dc} />
    </div>
  );
}
