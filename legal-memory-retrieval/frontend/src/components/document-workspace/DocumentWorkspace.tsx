import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** Chunks (or blocks) shown as one reader "part" when there is no real page count. */
export const PART_SIZE = 5;

type RightTab = "versions" | "info" | "ai";
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
  highlightChunk,
}: {
  doc: DocumentDetail;
  address: Address;
  setParams: ReturnType<typeof useSearchParams>[1];
  panelParam: string | null;
  highlightChunk?: string;
}) {
  const versions = useDocumentVersions(doc.document_id);
  const versionRows = versions.data ?? [];
  const currentVersionId = doc.current_version_id ?? versionRows[0]?.version_id;
  const openVersionId = address.versionId ?? currentVersionId;
  const openVersion = versionRows.find((v) => v.version_id === openVersionId) ?? doc.current_version;

  const chunkCount = doc.chunk_count ?? 0;
  const pageCountFromVersion = openVersion?.page_count ?? doc.page_count ?? null;
  // Real page numbers only when an original/rendition exists; otherwise label as Parts.
  const usePages =
    Boolean(doc.has_original) && typeof pageCountFromVersion === "number" && pageCountFromVersion > 0;
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
  const unitTotal = usePages
    ? pageCountFromVersion
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
      return true;
    },
    [setAddress, unitTotal],
  );

  const [leftTab, setLeftTab] = useState<LeftTab>("outline");
  const [rightTab, setRightTab] = useState<RightTab>(panelParam === "versions" ? "versions" : "info");
  const [leftOpen, setLeftOpen] = useState(true);
  const [rightOpen, setRightOpen] = useState(true);
  const [goOpen, setGoOpen] = useState(false);
  const workspaceRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (panelParam === "versions") {
      setRightTab("versions");
      setRightOpen(true);
    }
  }, [panelParam]);

  useEffect(() => {
    if (address.part !== part) setAddress({ part }, true);
  }, [address.part, part, setAddress]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (isTypingTarget(e.target)) return;
      const meta = e.metaKey || e.ctrlKey;
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
  const sectionLabel = useMemo(() => {
    const items = outline.data?.outline ?? [];
    if (!items.length) return null;
    const match = [...items].reverse().find((o) => (o.page_number || 1) <= part);
    return match
      ? match.section_id
        ? `${match.section_id} — ${match.section_title}`
        : match.section_title
      : null;
  }, [outline.data, part]);

  const newerAvailable =
    Boolean(currentVersionId) && Boolean(openVersionId) && currentVersionId !== openVersionId;

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
        onShowCurrent={() => currentVersionId && setAddress({ versionId: currentVersionId, part: 1 })}
        onToggleLeft={() => setLeftOpen((v) => !v)}
        onToggleRight={() => setRightOpen((v) => !v)}
        leftOpen={leftOpen}
        rightOpen={rightOpen}
      />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {leftOpen && (
          <aside
            className="hidden w-64 shrink-0 flex-col border-r border-border bg-card md:flex"
            data-testid="document-left-rail"
          >
            <div className="flex shrink-0 gap-1 border-b border-border px-2 py-1.5">
              <RailTab active={leftTab === "outline"} onClick={() => setLeftTab("outline")}>
                Outline
              </RailTab>
              <RailTab active={leftTab === "thumbnails"} onClick={() => setLeftTab("thumbnails")}>
                {unitLabel}s
              </RailTab>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto">
              {leftTab === "outline" ? (
                <OutlineList
                  items={outline.data?.outline ?? []}
                  loading={outline.isPending}
                  currentPart={part}
                  usePages={usePages}
                  onJump={(item) => {
                    setAddress({
                      part: item.page_number || 1,
                      blockId: item.block_id,
                    });
                  }}
                />
              ) : (
                <ThumbnailList
                  total={unitTotal}
                  current={part}
                  unitLabel={unitLabel}
                  onJump={(n) => goToPart(n, { allowClamp: true })}
                />
              )}
            </div>
          </aside>
        )}

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

        {rightOpen && (
          <aside
            className="hidden w-72 shrink-0 flex-col border-l border-border bg-card lg:flex"
            data-testid="document-right-rail"
          >
            <div className="flex shrink-0 gap-1 border-b border-border px-2 py-1.5">
              <RailTab active={rightTab === "versions"} onClick={() => setRightTab("versions")}>
                Versions
              </RailTab>
              <RailTab active={rightTab === "info"} onClick={() => setRightTab("info")}>
                Info
              </RailTab>
              <RailTab active={rightTab === "ai"} onClick={() => setRightTab("ai")}>
                AI
              </RailTab>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto p-4">
              {rightTab === "versions" && (
                <VersionsList
                  versions={versionRows}
                  currentVersionId={currentVersionId}
                  openVersionId={openVersionId}
                  loading={versions.isPending}
                  onOpen={(v) => setAddress({ versionId: v.version_id, part: 1 })}
                />
              )}
              {rightTab === "info" && (
                <InfoPanel doc={doc} openVersion={openVersion} unitTotal={unitTotal} unitLabel={unitLabel} />
              )}
              {rightTab === "ai" && (
                <div className="space-y-3 text-sm text-muted-foreground">
                  <p>Ask about this document in the Assistant, or ask the firm about its matter.</p>
                  <div className="flex flex-wrap gap-2">
                    <Button asChild variant="outline" size="sm">
                      <Link to={doc.matter_id ? `/chat?matter=${doc.matter_id}` : "/chat"}>Open Assistant</Link>
                    </Button>
                    {doc.matter_code && (
                      <Button asChild variant="outline" size="sm">
                        <Link to={`/ask?scope=${encodeURIComponent(doc.matter_code)}&scopeType=matter`}>Ask the Firm</Link>
                      </Button>
                    )}
                  </div>
                </div>
              )}
            </div>
          </aside>
        )}
      </div>

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
  onShowCurrent,
  onToggleLeft,
  onToggleRight,
  leftOpen,
  rightOpen,
}: {
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
  onShowCurrent: () => void;
  onToggleLeft: () => void;
  onToggleRight: () => void;
  leftOpen: boolean;
  rightOpen: boolean;
}) {
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
        className="hidden rounded-md p-1.5 text-muted-foreground hover:bg-secondary md:inline-flex"
        aria-label={leftOpen ? "Hide outline" : "Show outline"}
        onClick={onToggleLeft}
      >
        <Icon name="view_sidebar" style={{ fontSize: 20 }} />
      </button>

      <div className="min-w-0 flex-1">
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
        <Button type="button" variant="ghost" size="sm" onClick={onOpenGo} data-testid="document-go-to">
          Go to
        </Button>
      </div>

      <button
        type="button"
        className="hidden rounded-md p-1.5 text-muted-foreground hover:bg-secondary lg:inline-flex"
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
        heading: b.block_type === "heading" || Boolean(b.section_title),
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
            {!usePages && <span>Reader · no page rendition yet</span>}
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
                {p.heading && p.title && p.title !== p.text && (
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
        {items.map((item) => {
          const active = usePages && (item.page_number || 1) === currentPart;
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
                <div className="truncate font-medium">
                  {item.section_id ? `${item.section_id} ` : ""}
                  {item.section_title}
                </div>
                <div className="text-[11px] text-muted-foreground">
                  {usePages ? `Page ${item.page_number}` : "Jump"}
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
}: {
  total: number;
  current: number;
  unitLabel: string;
  onJump: (n: number) => void;
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
          onClick={() => onJump(n)}
          className={cn(
            "flex w-full items-center gap-2 rounded-md border border-border px-2 py-2 text-left text-xs",
            n === current ? "border-wine bg-wine-soft text-wine" : "bg-card hover:bg-secondary",
          )}
        >
          <span className="flex h-10 w-8 items-center justify-center rounded border border-dashed border-border bg-secondary text-[10px]">
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

function VersionsList({
  versions,
  currentVersionId,
  openVersionId,
  loading,
  onOpen,
}: {
  versions: DocVersion[];
  currentVersionId?: string | null;
  openVersionId?: string;
  loading: boolean;
  onOpen: (v: DocVersion) => void;
}) {
  if (loading) return <p className="text-xs text-muted-foreground">Loading versions…</p>;
  if (!versions.length) {
    return (
      <p className="text-xs text-muted-foreground">
        Single unversioned text — upload a file to start a version chain.
      </p>
    );
  }
  return (
    <div data-testid="document-versions">
      <SectionLabel>Version history</SectionLabel>
      <ol className="mt-3 space-y-1">
        {versions.map((v) => {
          const isOpen = v.version_id === openVersionId;
          const isCurrent = v.version_id === currentVersionId;
          return (
            <li key={v.version_id}>
              <button
                type="button"
                onClick={() => onOpen(v)}
                className={cn(
                  "w-full rounded-md border border-transparent px-3 py-2 text-left text-sm",
                  isOpen ? "border-border bg-wine-soft text-wine" : "hover:bg-secondary",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="font-medium">{v.version_label || `Version ${v.version_number ?? ""}`}</span>
                  {isCurrent && <span className="text-[10px] uppercase tracking-wide">Current</span>}
                </div>
                <div className="mt-0.5 text-xs text-muted-foreground">
                  {[v.author_name, v.version_status, v.created_at?.slice(0, 10)].filter(Boolean).join(" · ")}
                </div>
                {v.change_summary && (
                  <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">{v.change_summary}</p>
                )}
              </button>
            </li>
          );
        })}
      </ol>
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
              {openVersion.created_at.slice(0, 16).replace("T", " ")}
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
