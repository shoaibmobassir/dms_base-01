import { Suspense, lazy, useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import {
  useDocument,
  useDocumentBlocks,
  useDocumentChunks,
  useDocumentOutline,
  useDocumentVersions,
} from "@/api/resources";
import type { DocumentDetail, DocumentOutlineItem, DocVersion } from "@/api/types";
import { Icon, MonoId, SectionLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { PrivacyControl } from "@/components/editor/PrivacyControl";
import { ArchiveDocument } from "@/components/document-workspace/ArchiveDocument";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { downloadDocument } from "@/api/resources";
import { useApp } from "@/context/AppContext";
import { FindInDocument } from "@/components/document-workspace/FindInDocument";
import { CommentsPanel, SelectionComment, useDocComments } from "@/components/comments/DocComments";
import type { ViewerTarget } from "@/components/viewer/DocumentViewer";
import { useMediaQuery } from "@/lib/use-media-query";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";
import { HistoryPanel } from "@/components/document-workspace/HistoryPanel";
import { GripVertical, X } from "lucide-react";
import type { Attachment } from "@/api/types";
import { attachmentKey, attachmentLabel, hasPageDrag, pageAttachment, readPageDrag, startPageDrag, type PageDrag } from "@/lib/pageDrag";

/** Chunks (or blocks) shown as one reader "part" when there is no real page count. */
export const PART_SIZE = 5;

/** The page (or, without real pages, the reader part) an outline item is on. */
function unitOf(item: DocumentOutlineItem, usePages: boolean) {
  if (usePages || !item.sequence) return item.page_number || 1;
  return Math.max(1, Math.ceil(item.sequence / PART_SIZE));
}

/** "5. Remuneration" for a numbered section; an unnumbered heading's internal id (a slug) is not shown. */
function outlineLabel(item: DocumentOutlineItem) {
  const id = item.section_id ?? "";
  const numbered = /^(?:\d+(?:\.\d+)*|[IVXLCDM]+|[A-Z])$/.test(id);
  return numbered && !item.section_title.startsWith(id) ? `${id}. ${item.section_title}` : item.section_title;
}

const DocumentViewer = lazy(() => import("@/components/viewer/DocumentViewer").then((m) => ({ default: m.DocumentViewer })));

type RightTab = "comments" | "versions" | "info" | "ai";
type LeftTab = "outline" | "thumbnails";

type Address = {
  versionId: string | undefined;
  part: number;
  blockId: string | undefined;
  chunkId: string | undefined;
};

function parseAddress(params: URLSearchParams): Address {
  const partRaw = Number(params.get("page") ?? params.get("part") ?? "1");
  return {
    versionId: params.get("version") ?? undefined,
    part: Number.isFinite(partRaw) && partRaw >= 1 ? Math.floor(partRaw) : 1,
    blockId: params.get("block") ?? undefined,
    chunkId: params.get("chunk") ?? undefined,
  };
}

function isTypingTarget(el: EventTarget | null) {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

export function DocumentWorkspace({ documentId }: { documentId: string }) {
  const [params, setParams] = useSearchParams();
  const address = parseAddress(params);
  const doc = useDocument(documentId, { lean: true });

  return (
    <QueryState
      query={doc}
      loading={
        <div
          className="flex h-full items-center justify-center text-sm text-muted-foreground"
          data-testid="document-workspace-loading"
        >
          Opening document…
        </div>
      }
    >
      {(d) => (
        <WorkspaceFrame
          doc={d}
          address={address}
          setParams={setParams}
          panelParam={params.get("panel")}
          commentParam={params.get("comment")}
          highlightChunk={address.chunkId}
        />
      )}
    </QueryState>
  );
}

function WorkspaceFrame({
  doc,
  address,
  setParams,
  panelParam,
  commentParam,
  highlightChunk,
}: {
  doc: DocumentDetail;
  address: Address;
  setParams: ReturnType<typeof useSearchParams>[1];
  panelParam: string | null;
  /** A comment to open (a link from the Assistant's "comments added" card). */
  commentParam?: string | null;
  highlightChunk?: string;
}) {
  const versions = useDocumentVersions(doc.document_id);
  const versionRows = versions.data ?? [];
  const currentVersionId = doc.current_version_id ?? versionRows[0]?.version_id;
  const openVersionId = address.versionId ?? currentVersionId;
  const openVersion = versionRows.find((v) => v.version_id === openVersionId) ?? doc.current_version;

  const chunkCount = doc.chunk_count ?? 0;
  const pageCountFromVersion = openVersion?.page_count ?? doc.page_count ?? null;
  // The page as filed (rendered pages, comments) is the default; "Text" is the plain reading view.
  const [viewMode, setViewMode] = useState<"pages" | "text">("pages");
  const [pagesOff, setPagesOff] = useState(false); // the file could not be rendered as pages
  const [renderedPages, setRenderedPages] = useState<number | null>(null);
  const [jump, setJump] = useState<ViewerTarget | null>(null);
  const pagesMode = Boolean(doc.has_original) && viewMode === "pages" && !pagesOff;
  // Real page numbers only when pages are shown or an original/rendition exists; otherwise label as Parts.
  const usePages =
    pagesMode || (Boolean(doc.has_original) && typeof pageCountFromVersion === "number" && pageCountFromVersion > 0);
  const unitLabel = usePages ? "Page" : "Part";

  // Probe the open version for a total without loading the whole document.
  const unitsProbe = useDocumentBlocks(doc.document_id, openVersionId, {
    from: 0,
    limit: 1,
    enabled: Boolean(openVersionId) && !usePages,
  });
  const readerUnits =
    (unitsProbe.data?.total && unitsProbe.data.total > 0
      ? unitsProbe.data.total
      : null) ??
    (doc.block_count && doc.block_count > 0 ? doc.block_count : null) ??
    chunkCount;
  const unitTotal = pagesMode
    ? (renderedPages ?? pageCountFromVersion ?? Math.max(1, address.part))
    : usePages
      ? (pageCountFromVersion ?? 1)
      : Math.max(1, Math.ceil(readerUnits / PART_SIZE) || 1);

  const part = Math.min(Math.max(1, address.part), unitTotal);

  const setAddress = useCallback(
    (patch: Partial<Address> & { clearBlock?: boolean; clearChunk?: boolean }, replace = false) => {
      setParams(
        (prev) => {
          const next = new URLSearchParams(prev);
          const version = patch.versionId !== undefined ? patch.versionId : address.versionId;
          const nextPart = patch.part !== undefined ? patch.part : address.part;
          if (version) next.set("version", version);
          else next.delete("version");
          next.set("page", String(nextPart));
          if (patch.clearBlock) next.delete("block");
          else if (patch.blockId) next.set("block", patch.blockId);
          if (patch.clearChunk) next.delete("chunk");
          else if (patch.chunkId) next.set("chunk", patch.chunkId);
          return next;
        },
        { replace },
      );
    },
    [address.part, address.versionId, setParams],
  );

  const goToPart = useCallback(
    (n: number, opts?: { replace?: boolean; allowClamp?: boolean }) => {
      const floor = Math.floor(n);
      if (!Number.isFinite(floor)) return false;
      if ((floor < 1 || floor > unitTotal) && !opts?.allowClamp) return false;
      const clamped = Math.min(Math.max(1, floor), unitTotal);
      setAddress({ part: clamped, clearBlock: true, clearChunk: true }, opts?.replace);
      if (pagesMode) setJump({ page: clamped, quote: "", nonce: Date.now() });
      return true;
    },
    [setAddress, unitTotal, pagesMode],
  );

  const [leftTab, setLeftTab] = useState<LeftTab>("outline");
  const [rightTab, setRightTab] = useState<RightTab>(panelParam === "versions" ? "versions" : "comments");
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  // Below these widths the rails are drawers, opened from the toolbar.
  const isMd = useMediaQuery("(min-width: 768px)");
  const isLg = useMediaQuery("(min-width: 1024px)");
  const [leftSheet, setLeftSheet] = useState(false);
  const [rightSheet, setRightSheet] = useState(false);
  // "Review changes" opens History on what the current version changed against the one before it.
  const [reviewNonce, setReviewNonce] = useState(0);
  const [goOpen, setGoOpen] = useState(false);
  const [findOpen, setFindOpen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (panelParam === "versions" || panelParam === "comments") {
      setRightTab(panelParam);
      setRightOpen(true);
      setRightSheet(true);
    }
  }, [panelParam]);

  useEffect(() => {
    if (address.part !== part) setAddress({ part }, true);
  }, [address.part, part, setAddress]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      const meta = e.metaKey || e.ctrlKey;
      if (e.key === "/" && !meta) {
        e.preventDefault();
        setFindOpen(true);
        return;
      }
      if (e.key === "g" || e.key === "G" || (meta && (e.key === "g" || e.key === "G"))) {
        e.preventDefault();
        setGoOpen(true);
        return;
      }
      if (e.key === "ArrowLeft" || e.key === "PageUp") {
        e.preventDefault();
        goToPart(part - 1, { allowClamp: true });
        return;
      }
      if (e.key === "ArrowRight" || e.key === "PageDown") {
        e.preventDefault();
        goToPart(part + 1, { allowClamp: true });
        return;
      }
      if (e.key === "Home") {
        e.preventDefault();
        goToPart(1, { allowClamp: true });
        return;
      }
      if (e.key === "End") {
        e.preventDefault();
        goToPart(unitTotal, { allowClamp: true });
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [goToPart, part, unitTotal]);

  const outline = useDocumentOutline(doc.document_id, openVersionId);
  // Plain files with no headings have no outline: show only the page list.
  const hasOutline = outline.isPending || (outline.data?.outline?.length ?? 0) > 0;
  const railTab: LeftTab = hasOutline ? leftTab : "thumbnails";
  const sectionLabel = useMemo(() => {
    const items = outline.data?.outline ?? [];
    if (!items.length) return null;
    const match = items.find((o) => unitOf(o, usePages) === part) ?? [...items].reverse().find((o) => unitOf(o, usePages) < part);
    return match
      ? match.section_id
        ? `${match.section_id} — ${match.section_title}`
        : match.section_title
      : null;
  }, [outline.data, part, usePages]);

  const newerAvailable =
    Boolean(currentVersionId) && Boolean(openVersionId) && currentVersionId !== openVersionId;
  // Comments are made on the current version, on pages as filed.
  const dc = useDocComments({ documentId: doc.document_id, versionId: address.versionId, canAdd: pagesMode && !newerAvailable });
  const viewerTarget = jump && (!dc.target || jump.nonce > dc.target.nonce) ? jump : dc.target;

  // Arriving from a link to one comment: open the comments, and mark that thread's text.
  const openedComment = useRef<string | null>(null);
  useEffect(() => {
    if (!commentParam || openedComment.current === commentParam || !pagesMode) return;
    const thread = dc.threads.find((t) => t.comment_id === commentParam);
    if (!thread) return;
    openedComment.current = commentParam;
    setRightTab("comments");
    setRightOpen(true);
    dc.focusThread(thread);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [commentParam, dc.threads, pagesMode]);

  // Dragging this page to the Assistant: in Pages mode it is the page as rendered; otherwise the reader's page or part.
  const dragCurrent: PageDrag = {
    document_id: doc.document_id,
    filename: doc.title,
    unit: usePages || pagesMode ? "page" : "part",
    number: part,
    version_id: openVersionId,
    part_size: PART_SIZE,
    rendered: pagesMode,
  };

  const leftRail = (
    <>
      <div className="flex shrink-0 gap-1 border-b border-border px-2 py-1.5">
        {hasOutline && (
          <RailTab active={railTab === "outline"} onClick={() => setLeftTab("outline")}>
            Outline
          </RailTab>
        )}
        <RailTab active={railTab === "thumbnails"} onClick={() => setLeftTab("thumbnails")}>
          {unitLabel}s
        </RailTab>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {railTab === "outline" ? (
          <OutlineList
            items={outline.data?.outline ?? []}
            loading={outline.isPending}
            currentPart={part}
            usePages={usePages}
            onJump={(item) => {
              setAddress({
                part: unitOf(item, usePages),
                blockId: item.block_id,
              });
              if (pagesMode) setJump({ page: item.page_number || 1, quote: "", nonce: Date.now() });
            }}
          />
        ) : (
          <ThumbnailList
            total={unitTotal}
            current={part}
            unitLabel={unitLabel}
            onJump={(n) => goToPart(n, { allowClamp: true })}
            dragOf={(n) => ({ ...dragCurrent, number: n })}
          />
        )}
      </div>
    </>
  );
  const openThreads = dc.threads.filter((t) => t.status === "open").length;
  const rightRail = (
    <>
      <div className="flex shrink-0 gap-1 border-b border-border px-2 py-1.5">
        <RailTab active={rightTab === "comments"} onClick={() => setRightTab("comments")}>
          Comments{openThreads > 0 ? ` ${openThreads}` : ""}
        </RailTab>
        <RailTab active={rightTab === "versions"} onClick={() => setRightTab("versions")}>
          History
        </RailTab>
        <RailTab active={rightTab === "info"} onClick={() => setRightTab("info")}>
          Info
        </RailTab>
        <RailTab active={rightTab === "ai"} onClick={() => setRightTab("ai")}>
          Assistant
        </RailTab>
      </div>
      <div className={cn("min-h-0 flex-1", rightTab === "comments" ? "flex flex-col overflow-hidden" : "overflow-y-auto p-4")}>
        {rightTab === "comments" && (
          <CommentsPanel
            dc={dc}
            onViewVersion={(versionId) => setAddress({ versionId })}
            note={
              !pagesMode
                ? "Switch to Pages to comment on the document as filed."
                : newerAvailable
                  ? "You are reading an earlier version. Comments are added on the current one."
                  : undefined
            }
          />
        )}
        {rightTab === "versions" && (
          <HistoryPanel
            reviewNonce={reviewNonce}
            documentId={doc.document_id}
            openVersionId={openVersionId}
            onOpen={(versionId) => setAddress({ versionId })}
          />
        )}
        {rightTab === "info" && (
          <InfoPanel doc={doc} openVersion={openVersion} unitTotal={unitTotal} unitLabel={unitLabel} />
        )}
        {rightTab === "ai" && (
          <div className="space-y-4 text-sm" data-testid="document-ai">
            <p className="text-muted-foreground">
              The Assistant reads this document and can add comments, suggest edits and draft changes. It opens with the document attached.
            </p>
            <AssistantAsk doc={doc} current={dragCurrent} />
            <div className="flex flex-col gap-1.5">
              {AI_TASKS.map((t) => (
                <Link
                  key={t.label}
                  to={assistantLink(doc, t.prompt)}
                  data-testid="document-ai-task"
                  className="flex items-center gap-2 rounded-md border border-border px-3 py-2 hover:bg-secondary"
                >
                  <Icon name={t.icon} className="text-wine" style={{ fontSize: 18 }} />
                  {t.label}
                </Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </>
  );

  return (
    <div
      ref={workspaceRef}
      tabIndex={-1}
      className="flex h-full min-h-0 flex-col overflow-hidden outline-none"
      data-testid="document-workspace"
    >
      <Toolbar
        doc={doc}
        openVersion={openVersion}
        openVersionId={openVersionId}
        newerAvailable={newerAvailable}
        unitLabel={unitLabel}
        part={part}
        unitTotal={unitTotal}
        sectionLabel={sectionLabel}
        onPrev={() => goToPart(part - 1, { allowClamp: true })}
        onNext={() => goToPart(part + 1, { allowClamp: true })}
        onJump={(n) => goToPart(n)}
        onOpenGo={() => setGoOpen(true)}
        onOpenFind={() => setFindOpen((v) => !v)}
        viewMode={pagesMode ? "pages" : "text"}
        onViewMode={doc.has_original && !pagesOff ? setViewMode : undefined}
        onShowCurrent={() => currentVersionId && setAddress({ versionId: currentVersionId })}
        dragCurrent={dragCurrent}
        canReview={versionRows.length > 1 && !newerAvailable}
        onReview={() => {
          setRightTab("versions");
          if (isLg) setRightOpen(true);
          else setRightSheet(true);
          setReviewNonce((n) => n + 1);
        }}
        onToggleLeft={() => (isMd ? setLeftOpen((v) => !v) : setLeftSheet((v) => !v))}
        onToggleRight={() => (isLg ? setRightOpen((v) => !v) : setRightSheet((v) => !v))}
        leftOpen={isMd ? leftOpen : leftSheet}
        rightOpen={isLg ? rightOpen : rightSheet}
      />

      {findOpen && (
        <FindInDocument
          documentId={doc.document_id}
          versionId={openVersionId}
          onClose={() => setFindOpen(false)}
          onPick={(m) => {
            const target = Math.min(Math.max(1, usePages ? m.page_number || 1 : Math.floor(m.index / PART_SIZE) + 1), unitTotal);
            setAddress({ part: target, blockId: m.block_id, clearChunk: true });
            if (pagesMode) setJump({ page: target, quote: "", nonce: Date.now() });
          }}
        />
      )}

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {isMd && leftOpen && (
          <aside
            className="flex w-64 shrink-0 flex-col border-r border-border bg-card"
            data-testid="document-left-rail"
          >
            {leftRail}
          </aside>
        )}

        {pagesMode ? (
          <section
            className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-secondary/30"
            data-testid="document-canvas"
            aria-label={`${unitLabel} ${part} of ${unitTotal}`}
          >
            <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Opening the pages…</p>}>
              <DocumentViewer
                key={openVersionId ?? "current"}
                src={`/api/documents/${encodeURIComponent(doc.document_id)}/render${openVersionId ? `?version_id=${encodeURIComponent(openVersionId)}` : ""}`}
                startPage={address.part}
                hideNav
                target={viewerTarget}
                marks={dc.marks}
                onMarkClick={(cid) => {
                  dc.setActive(cid);
                  setRightTab("comments");
                  setRightOpen(true);
                  document.getElementById(`comment-${cid}`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
                }}
                onMarksLocated={dc.setLocated}
                onSelectText={dc.onSelectText}
                onPageChange={(p) => {
                  if (p !== address.part) setAddress({ part: p }, true);
                }}
                onDocument={(n) => setRenderedPages(n)}
                onUnavailable={() => setPagesOff(true)}
              />
            </Suspense>
          </section>
        ) : (
          <ReaderCanvas
            documentId={doc.document_id}
            versionId={openVersionId}
            part={part}
            partSize={PART_SIZE}
            usePages={usePages}
            unitLabel={unitLabel}
            unitTotal={unitTotal}
            highlightChunk={highlightChunk}
            highlightBlock={address.blockId}
          />
        )}

        {isLg && rightOpen && (
          <aside
            className="flex w-80 shrink-0 flex-col border-l border-border bg-card"
            data-testid="document-right-rail"
          >
            {rightRail}
          </aside>
        )}
      </div>

      <Sheet open={!isMd && leftSheet} onOpenChange={setLeftSheet}>
        <SheetContent side="left" className="flex w-[320px] max-w-[90vw] flex-col gap-0 p-0" aria-describedby={undefined}>
          <SheetTitle className="sr-only">Outline</SheetTitle>
          <div className="flex min-h-0 flex-1 flex-col pt-10" data-testid="document-left-sheet">
            {leftRail}
          </div>
        </SheetContent>
      </Sheet>
      <Sheet open={!isLg && rightSheet} onOpenChange={setRightSheet}>
        <SheetContent side="right" className="flex w-[360px] max-w-[92vw] flex-col gap-0 p-0" aria-describedby={undefined}>
          <SheetTitle className="sr-only">Versions and details</SheetTitle>
          <div className="flex min-h-0 flex-1 flex-col pt-10" data-testid="document-right-sheet">
            {rightRail}
          </div>
        </SheetContent>
      </Sheet>

      <SelectionComment dc={dc} />

      <GoToDialog
        open={goOpen}
        onOpenChange={setGoOpen}
        unitLabel={unitLabel}
        unitTotal={unitTotal}
        current={part}
        onGo={(n) => {
          const ok = goToPart(n);
          if (ok) setGoOpen(false);
          return ok;
        }}
      />
    </div>
  );
}

/**
 * Ask the Assistant anything about this document: it opens with the document attached and answers at once. Pages
 * dragged here (from the page list or the grip by the page number) go with the question instead of the whole document,
 * so "this page" means exactly what was on screen.
 */
function AssistantAsk({ doc, current }: { doc: DocumentDetail; current: PageDrag }) {
  const navigate = useNavigate();
  const [text, setText] = useState("");
  const [pages, setPages] = useState<Attachment[]>([]);
  const [over, setOver] = useState(false);
  const add = (p: PageDrag) =>
    setPages((list) => (list.some((a) => attachmentKey(a) === attachmentKey(pageAttachment(p))) ? list : [...list, pageAttachment(p)]));
  const go = () => {
    const q = text.trim();
    if (!q) return;
    navigate(assistantLink(doc, q, true), pages.length ? { state: { handoff: { pages } } } : undefined);
  };
  return (
    <div
      onDragOver={(e) => {
        if (!hasPageDrag(e)) return;
        e.preventDefault();
        e.dataTransfer.dropEffect = "copy";
        setOver(true);
      }}
      onDragLeave={(e) => {
        if (!e.currentTarget.contains(e.relatedTarget as Node | null)) setOver(false);
      }}
      onDrop={(e) => {
        setOver(false);
        const p = readPageDrag(e);
        if (!p) return;
        e.preventDefault();
        add(p);
      }}
      className={cn(
        "rounded-2xl border border-border bg-card p-2 focus-within:border-wine/50 focus-within:ring-2 focus-within:ring-wine/10",
        over && "border-wine ring-2 ring-wine/30",
      )}
      data-testid="document-ai-ask"
    >
      {pages.length > 0 && (
        <ul className="flex flex-wrap gap-1.5 px-1 pb-1.5" data-testid="assistant-pages">
          {pages.map((a) => (
            <li key={attachmentKey(a)} className="inline-flex items-center gap-1 rounded-full border border-border bg-secondary/60 py-0.5 pl-2 pr-0.5 text-xs">
              <span className="max-w-[180px] truncate">{attachmentLabel(a)}</span>
              <button
                type="button"
                aria-label={`Remove ${attachmentLabel(a)}`}
                onClick={() => setPages((list) => list.filter((x) => attachmentKey(x) !== attachmentKey(a)))}
                className="rounded-full p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
              >
                <X className="h-3 w-3" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
            e.preventDefault();
            go();
          }
        }}
        rows={2}
        placeholder={over ? "Drop the page to ask about it" : "Ask about this document, or drag a page here and say what to change…"}
        aria-label="Ask the Assistant about this document"
        data-testid="document-ai-input"
        className="w-full resize-none bg-transparent px-2 py-1 text-sm focus:outline-none"
      />
      <div className="flex items-center justify-between gap-2">
        <button
          type="button"
          onClick={() => add(current)}
          data-testid="assistant-add-current"
          className="rounded-full px-2 py-1 text-xs text-muted-foreground hover:bg-secondary hover:text-foreground"
        >
          + {current.unit === "page" ? "Page" : "Part"} {current.number}
        </button>
        <button
          type="button"
          onClick={go}
          disabled={!text.trim()}
          aria-label="Send to the Assistant"
          data-testid="document-ai-send"
          className="flex h-8 w-8 items-center justify-center rounded-full bg-primary text-primary-foreground disabled:bg-secondary disabled:text-muted-foreground"
        >
          <Icon name="arrow_upward" style={{ fontSize: 18 }} />
        </button>
      </div>
    </div>
  );
}

const AI_TASKS = [
  { label: "Review and add comments", icon: "add_comment", prompt: "Review this document and add comments on the key risks, ambiguities and anything I should confirm. Quote the exact wording each comment is about." },
  { label: "Suggest edits", icon: "edit_note", prompt: "Suggest edits that improve this document as cards I can accept or reject; accepting writes the change into the document." },
  { label: "Summarise this document", icon: "summarize", prompt: "Summarise this document: the parties, what it does and anything that needs attention." },
  { label: "List obligations and deadlines", icon: "checklist", prompt: "List every obligation, deadline and condition in this document, with the clause that creates each." },
];

/** An Assistant conversation limited to the document's matter, with the document attached and a starting prompt. */
function assistantLink(doc: DocumentDetail, prompt: string, send = false) {
  const q = new URLSearchParams({ doc: doc.document_id, docTitle: doc.title, q: prompt });
  if (send) q.set("send", "1"); // a question typed here is sent at once; a starter prompt only fills the box
  if (doc.matter_id) q.set("matter", doc.matter_id);
  return `/chat?${q.toString()}`;
}

function Toolbar({
  doc,
  openVersion,
  openVersionId,
  newerAvailable,
  unitLabel,
  part,
  unitTotal,
  sectionLabel,
  onPrev,
  onNext,
  onJump,
  onOpenGo,
  onOpenFind,
  viewMode,
  onViewMode,
  onShowCurrent,
  dragCurrent,
  canReview,
  onReview,
  onToggleLeft,
  onToggleRight,
  leftOpen,
  rightOpen,
}: {
  /** What dragging the page being read to the Assistant carries. */
  dragCurrent: PageDrag;
  canReview: boolean;
  onReview: () => void;
  doc: DocumentDetail;
  openVersion?: DocVersion | DocumentDetail["current_version"];
  openVersionId?: string;
  newerAvailable: boolean;
  unitLabel: string;
  part: number;
  unitTotal: number;
  sectionLabel: string | null;
  onPrev: () => void;
  onNext: () => void;
  onJump: (n: number) => boolean | void;
  onOpenGo: () => void;
  onOpenFind: () => void;
  viewMode: "pages" | "text";
  /** Present when the file can be shown as pages: switches between Pages and Text. */
  onViewMode?: (mode: "pages" | "text") => void;
  onShowCurrent: () => void;
  onToggleLeft: () => void;
  onToggleRight: () => void;
  leftOpen: boolean;
  rightOpen: boolean;
}) {
  const { toast } = useApp();
  const [draft, setDraft] = useState(String(part));
  useEffect(() => setDraft(String(part)), [part]);

  const commit = () => {
    const n = Number(draft);
    if (!Number.isFinite(n)) {
      setDraft(String(part));
      return;
    }
    const ok = onJump(Math.floor(n));
    if (ok === false) setDraft(String(part));
  };

  const versionLabel =
    openVersion?.version_label ||
    (openVersion?.version_number != null
      ? `v${openVersion.version_number}`
      : openVersionId
        ? "Version"
        : "—");
  const status = openVersion?.version_status;

  return (
    <header
      className="flex shrink-0 flex-wrap items-center gap-3 border-b border-border bg-card px-3 py-2"
      data-testid="document-toolbar"
    >
      <button
        type="button"
        className="inline-flex rounded-md p-2 text-muted-foreground hover:bg-secondary"
        aria-label={leftOpen ? "Hide outline" : "Show outline"}
        onClick={onToggleLeft}
      >
        <Icon name="view_sidebar" style={{ fontSize: 20 }} />
      </button>

      <div className="min-w-0 flex-1 basis-[calc(100%-3rem)] sm:basis-0">
        <div className="flex flex-wrap items-baseline gap-2">
          <h1 className="truncate font-display text-lg text-ink" data-testid="document-title">
            {doc.title}
          </h1>
          <span
            className={cn(
              "shrink-0 rounded-md border border-border px-2 py-0.5 text-xs",
              newerAvailable && "border-wine/40 bg-wine-soft text-wine",
            )}
            data-testid="document-version-chip"
          >
            {versionLabel}
            {status ? ` · ${status}` : ""}
            {newerAvailable ? " · newer version available" : ""}
          </span>
          {newerAvailable && (
            <button type="button" className="text-xs text-wine hover:underline" onClick={onShowCurrent}>
              Show current
            </button>
          )}
        </div>
        <div className="mt-0.5 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
          <MonoId>{doc.document_id}</MonoId>
          {doc.matter_id && (
            <Link to={`/matters/${doc.matter_id}`} className="text-wine hover:underline">
              {doc.matter_info?.title ?? doc.matter_code}
            </Link>
          )}
          {sectionLabel && (
            <span className="truncate" title={sectionLabel}>
              {sectionLabel}
            </span>
          )}
        </div>
      </div>

      <div className="flex items-center gap-1" data-testid="document-page-nav">
        <span
          draggable
          onDragStart={(e) => startPageDrag(e, dragCurrent)}
          title={`Drag this ${unitLabel.toLowerCase()} to the Assistant`}
          aria-label={`Drag ${unitLabel.toLowerCase()} ${part} to the Assistant`}
          data-testid="page-handle"
          className="inline-flex h-9 cursor-grab items-center rounded-md px-1 text-muted-foreground hover:bg-secondary active:cursor-grabbing"
        >
          <GripVertical className="h-4 w-4" />
        </span>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={`Previous ${unitLabel.toLowerCase()}`}
          disabled={part <= 1}
          onClick={onPrev}
        >
          <Icon name="chevron_left" style={{ fontSize: 20 }} />
        </Button>
        <div className="flex items-center gap-1 rounded-md border border-border px-2 py-1 text-sm">
          <span className="sr-only">{unitLabel}</span>
          <Input
            type="text"
            inputMode="numeric"
            aria-label={`${unitLabel} number`}
            value={draft}
            onChange={(e) => setDraft(e.target.value.replace(/[^\d]/g, ""))}
            onBlur={commit}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                commit();
              }
            }}
            className="h-7 w-12 border-0 bg-transparent p-0 text-center shadow-none focus-visible:ring-0"
            data-testid="document-page-input"
          />
          <span className="text-muted-foreground">/ {unitTotal.toLocaleString()}</span>
        </div>
        <Button
          type="button"
          variant="outline"
          size="icon"
          aria-label={`Next ${unitLabel.toLowerCase()}`}
          disabled={part >= unitTotal}
          onClick={onNext}
        >
          <Icon name="chevron_right" style={{ fontSize: 20 }} />
        </Button>
        <Button type="button" variant="ghost" size="icon" aria-label="Find in document (/)" onClick={onOpenFind} data-testid="document-find">
          <Icon name="search" style={{ fontSize: 20 }} />
        </Button>
        <Button type="button" variant="ghost" size="sm" onClick={onOpenGo} data-testid="document-go-to">
          Go to
        </Button>
      </div>

      {onViewMode && (
        <div className="inline-flex overflow-hidden rounded-md border border-border text-xs" role="tablist" aria-label="View" data-testid="document-view-mode">
          {(["pages", "text"] as const).map((m) => (
            <button
              key={m}
              type="button"
              role="tab"
              aria-selected={viewMode === m}
              onClick={() => onViewMode(m)}
              data-testid={`document-view-${m}`}
              className={cn("px-2.5 py-1.5 font-medium capitalize", viewMode === m ? "bg-wine-soft text-wine" : "text-muted-foreground hover:bg-secondary")}
            >
              {m}
            </button>
          ))}
        </div>
      )}
      {doc.has_original && (
        <Button
          type="button"
          variant="outline"
          size="sm"
          onClick={() =>
            void downloadDocument(doc.document_id, openVersionId).catch((err) =>
              toast(err instanceof Error ? err.message : "The download failed"),
            )
          }
          data-testid="document-download"
        >
          <Icon name="download" style={{ fontSize: 16 }} /> Download
        </Button>
      )}
      <PrivacyControl documentId={doc.document_id} />
      {canReview && (
        <Button type="button" size="sm" variant="outline" onClick={onReview} data-testid="document-review-changes">
          <Icon name="difference" style={{ fontSize: 16 }} /> Review changes
        </Button>
      )}
      {doc.matter_id && <ArchiveDocument documentId={doc.document_id} matterId={doc.matter_id} title={doc.title} />}
      <Button asChild size="sm" variant="outline" data-testid="document-edit">
        <Link to={`/documents/${encodeURIComponent(doc.document_id)}/edit`}>
          <Icon name="edit_document" style={{ fontSize: 16 }} /> Edit
        </Link>
      </Button>

      <button
        type="button"
        className="inline-flex rounded-md p-2 text-muted-foreground hover:bg-secondary"
        aria-label={rightOpen ? "Hide panel" : "Show panel"}
        onClick={onToggleRight}
      >
        <Icon name="right_panel_open" style={{ fontSize: 20 }} />
      </button>
    </header>
  );
}

function ReaderCanvas({
  documentId,
  versionId,
  part,
  partSize,
  usePages,
  unitLabel,
  unitTotal,
  highlightChunk,
  highlightBlock,
}: {
  documentId: string;
  versionId?: string;
  part: number;
  partSize: number;
  usePages: boolean;
  unitLabel: string;
  unitTotal: number;
  highlightChunk?: string;
  highlightBlock?: string;
}) {
  const blocksQuery = useDocumentBlocks(documentId, versionId, {
    from: usePages ? 0 : (part - 1) * partSize,
    limit: usePages ? 200 : partSize,
    enabled: Boolean(versionId),
  });
  const chunkOffset = (part - 1) * partSize;
  const blockTotal = blocksQuery.data?.total ?? 0;
  const preferChunks = !versionId || (!blocksQuery.isPending && blockTotal === 0);
  const chunksQuery = useDocumentChunks(documentId, {
    offset: chunkOffset,
    limit: partSize,
    enabled: preferChunks,
  });

  const blocks = blocksQuery.data?.blocks ?? [];
  const pageBlocks = usePages ? blocks.filter((b) => (b.page_number ?? 1) === part) : blocks;
  const useBlockView = Boolean(versionId) && blockTotal > 0;
  const passages = useBlockView
    ? pageBlocks.map((b) => ({
        id: b.block_id,
        text: b.text,
        heading: b.block_type === "heading",
        title: b.section_title,
      }))
    : (chunksQuery.data?.chunks ?? []).map((c) => ({
        id: c.chunk_id,
        text: c.text,
        heading: false,
        title: undefined as string | undefined,
      }));

  const loading = useBlockView ? blocksQuery.isPending : chunksQuery.isPending;
  const highlightId = highlightBlock ?? highlightChunk;

  return (
    <section
      className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-secondary/30"
      data-testid="document-canvas"
      aria-label={`${unitLabel} ${part} of ${unitTotal}`}
    >
      <div className="min-h-0 flex-1 overflow-y-auto">
        <article className="mx-auto my-6 max-w-3xl rounded-lg border border-border bg-card px-8 py-10 shadow-sm lg:px-12">
          <div className="mb-6 flex items-center justify-between text-xs text-muted-foreground">
            <span>
              {unitLabel} {part.toLocaleString()} of {unitTotal.toLocaleString()}
            </span>
            {!usePages && <span>Text view</span>}
          </div>

          {loading && <p className="text-sm text-muted-foreground">Loading…</p>}
          {!loading && passages.length === 0 && (
            <p className="text-sm text-muted-foreground">No text for this {unitLabel.toLowerCase()}.</p>
          )}
          <div className="space-y-5" data-testid="document-body">
            {passages.map((p) => (
              <div
                key={p.id}
                id={`passage-${p.id}`}
                ref={(el) => {
                  if (el && p.id === highlightId) el.scrollIntoView({ block: "center" });
                }}
                className={cn(
                  p.heading && "font-display text-xl text-ink",
                  p.id === highlightId && "-mx-3 rounded-md bg-wine-soft px-3 py-2",
                )}
              >
                {p.heading && p.title && !p.text.toLowerCase().includes(p.title.toLowerCase()) && (
                  <div className="mb-1 text-xs uppercase tracking-wide text-muted-foreground">{p.title}</div>
                )}
                <p className="whitespace-pre-wrap text-[15px] leading-[1.8] text-foreground/90">{p.text}</p>
              </div>
            ))}
          </div>
        </article>
      </div>
    </section>
  );
}

function OutlineList({
  items,
  loading,
  currentPart,
  usePages,
  onJump,
}: {
  items: DocumentOutlineItem[];
  loading: boolean;
  currentPart: number;
  usePages: boolean;
  onJump: (item: DocumentOutlineItem) => void;
}) {
  if (loading) return <p className="p-4 text-xs text-muted-foreground">Loading outline…</p>;
  if (!items.length) {
    return (
      <p className="p-4 text-xs text-muted-foreground">
        Structure is not ready yet. Headings appear when this version has been processed.
      </p>
    );
  }
  return (
    <nav className="py-2" aria-label="Document outline" data-testid="document-outline">
      <div className="meta-label px-4 pb-2">Document structure</div>
      <ul className="space-y-0.5 px-2">
        {items.map((item, idx) => {
          // Only the section the reader is in: the last heading that starts on or before this page.
          const activeIdx = items.reduce((acc, it, i) => (unitOf(it, usePages) <= currentPart ? i : acc), -1);
          const active = idx === activeIdx;
          return (
            <li key={item.block_id}>
              <button
                type="button"
                onClick={() => onJump(item)}
                className={cn(
                  "w-full rounded-md px-2 py-1.5 text-left text-sm",
                  active ? "bg-wine-soft text-wine" : "hover:bg-secondary",
                )}
              >
                <div className="truncate font-medium">{outlineLabel(item)}</div>
                <div className="text-xs text-muted-foreground">
                  {usePages ? `Page ${item.page_number}` : `Part ${unitOf(item, false)}`}
                </div>
              </button>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

function ThumbnailList({
  total,
  current,
  unitLabel,
  onJump,
  dragOf,
}: {
  total: number;
  current: number;
  unitLabel: string;
  onJump: (n: number) => void;
  /** What dragging page n to the Assistant carries. */
  dragOf: (n: number) => PageDrag;
}) {
  const windowSize = 40;
  const start = Math.max(1, current - windowSize);
  const end = Math.min(total, current + windowSize);
  const items: number[] = [];
  for (let i = start; i <= end; i++) items.push(i);

  return (
    <div className="space-y-1 p-2" data-testid="document-thumbnails">
      <div className="meta-label px-2 pb-2">
        {unitLabel}s {start}–{end} of {total}
      </div>
      {start > 1 && (
        <button
          type="button"
          className="w-full py-1 text-xs text-wine"
          onClick={() => onJump(Math.max(1, start - windowSize))}
        >
          Earlier…
        </button>
      )}
      {items.map((n) => (
        <button
          key={n}
          type="button"
          draggable
          onDragStart={(e) => startPageDrag(e, dragOf(n))}
          title={`Drag ${unitLabel.toLowerCase()} ${n} to the Assistant`}
          data-testid="page-thumb"
          onClick={() => onJump(n)}
          className={cn(
            "flex w-full cursor-grab items-center gap-2 rounded-md border border-border px-2 py-2 text-left text-xs active:cursor-grabbing",
            n === current ? "border-wine bg-wine-soft text-wine" : "bg-card hover:bg-secondary",
          )}
        >
          <span className="flex h-10 w-8 items-center justify-center rounded border border-dashed border-border bg-secondary text-xs">
            {n}
          </span>
          {unitLabel} {n}
        </button>
      ))}
      {end < total && (
        <button
          type="button"
          className="w-full py-1 text-xs text-wine"
          onClick={() => onJump(Math.min(total, end + 1))}
        >
          Later…
        </button>
      )}
    </div>
  );
}

function InfoPanel({
  doc,
  openVersion,
  unitTotal,
  unitLabel,
}: {
  doc: DocumentDetail;
  openVersion?: DocVersion | DocumentDetail["current_version"];
  unitTotal: number;
  unitLabel: string;
}) {
  return (
    <div className="space-y-4 text-sm" data-testid="document-info">
      <div>
        <SectionLabel>Document</SectionLabel>
        <p className="mt-1 font-medium">{doc.title}</p>
        <p className="text-xs text-muted-foreground">{doc.document_type}</p>
      </div>
      <div>
        <SectionLabel>{unitLabel}s</SectionLabel>
        <p className="mt-1">{unitTotal.toLocaleString()}</p>
      </div>
      {openVersion && (
        <div>
          <SectionLabel>Open version</SectionLabel>
          <p className="mt-1">
            {openVersion.version_label || `Version ${openVersion.version_number ?? ""}`}
            {openVersion.version_status ? ` · ${openVersion.version_status}` : ""}
          </p>
          {openVersion.author_name && (
            <p className="text-xs text-muted-foreground">{openVersion.author_name}</p>
          )}
          {openVersion.created_at && (
            <p className="text-xs text-muted-foreground">
              {formatDateTime(openVersion.created_at)}
            </p>
          )}
          {"change_summary" in openVersion && openVersion.change_summary && (
            <p className="mt-2 text-xs text-muted-foreground">{openVersion.change_summary}</p>
          )}
        </div>
      )}
      <div>
        <SectionLabel>Original file</SectionLabel>
        <p className="mt-1 text-muted-foreground">
          {doc.has_original ? "Stored" : "No original on file — reader only"}
        </p>
      </div>
      {doc.matter_id && (
        <div>
          <SectionLabel>Matter</SectionLabel>
          <Link to={`/matters/${doc.matter_id}`} className="mt-1 block text-wine hover:underline">
            {doc.matter_info?.title ?? doc.matter_code}
          </Link>
        </div>
      )}
    </div>
  );
}

function GoToDialog({
  open,
  onOpenChange,
  unitLabel,
  unitTotal,
  current,
  onGo,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  unitLabel: string;
  unitTotal: number;
  current: number;
  onGo: (n: number) => boolean;
}) {
  const [value, setValue] = useState(String(current));
  const [error, setError] = useState(false);
  useEffect(() => {
    if (open) {
      setValue(String(current));
      setError(false);
    }
  }, [open, current]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-sm" data-testid="document-go-dialog">
        <DialogHeader>
          <DialogTitle>Go to {unitLabel.toLowerCase()}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-3"
          onSubmit={(e) => {
            e.preventDefault();
            const n = Number(value);
            const ok = Number.isFinite(n) && onGo(Math.floor(n));
            setError(!ok);
          }}
        >
          <Input
            autoFocus
            inputMode="numeric"
            aria-label={`${unitLabel} number`}
            value={value}
            onChange={(e) => {
              setValue(e.target.value.replace(/[^\d]/g, ""));
              setError(false);
            }}
            data-testid="document-go-input"
          />
          <p className="text-xs text-muted-foreground">
            Enter a number from 1 to {unitTotal.toLocaleString()}.
          </p>
          {error && (
            <p className="text-xs text-destructive">That {unitLabel.toLowerCase()} is out of range.</p>
          )}
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>
              Cancel
            </Button>
            <Button type="submit">Go</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

function RailTab({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "rounded-md px-2.5 py-1 text-xs font-medium",
        active ? "bg-secondary text-ink" : "text-muted-foreground hover:text-ink",
      )}
    >
      {children}
    </button>
  );
}
