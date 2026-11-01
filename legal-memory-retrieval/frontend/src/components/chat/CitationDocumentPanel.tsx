import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Download, ExternalLink, FileText, X } from "lucide-react";
import { apiFetch, authHeaders } from "@/api/client";
import { useDocument } from "@/api/resources";
import type { Citation } from "@/api/types";
import type { LocateResult, ViewerTarget } from "@/components/viewer/DocumentViewer";
import { firstPage } from "@/components/viewer/findQuote";
import { cn } from "@/lib/utils";

// pdf.js is large: load the viewer the first time a document is opened.
const DocumentViewer = lazy(() => import("@/components/viewer/DocumentViewer").then((m) => ({ default: m.DocumentViewer })));

// ── what the panel shows ──────────────────────────────────────────────────────

export type SourceQuote = { page: number | null; quote: string; verified?: boolean | null };

/** A document to show beside the chat, optionally with passages to highlight. */
export type PanelSource = {
  documentId: string;
  title?: string;
  label: string;
  quotes: SourceQuote[];
  startAt?: number;
  /** Generated files are not firm documents: no workspace link. */
  generated?: boolean;
  /** Changes on every open so repeat clicks re-run the jump. */
  nonce: number;
};

function quotesOf(c: Citation): SourceQuote[] {
  const raw = Array.isArray(c.quotes) ? (c.quotes as Record<string, unknown>[]) : [];
  const list = raw
    .filter((q) => typeof q?.quote === "string" && (q.quote as string).trim())
    .map((q) => ({
      page: firstPage(q.page),
      quote: String(q.quote),
      verified: (q.verification as { verified?: boolean } | undefined)?.verified ?? null,
    }));
  if (list.length) return list;
  const single = typeof c.quote === "string" ? c.quote : typeof c.snippet === "string" ? c.snippet : "";
  return single ? [{ page: firstPage(c.page), quote: single, verified: typeof c.verified === "boolean" ? c.verified : null }] : [];
}

export function sourceFromCitation(c: Citation, nonce: number): PanelSource | null {
  const documentId = String(c.document_id ?? "");
  if (!documentId) return null;
  return {
    documentId,
    title: typeof c.title === "string" ? c.title : undefined,
    label: c.ref != null ? `Source [${String(c.ref)}]` : "Cited passage",
    quotes: quotesOf(c),
    nonce,
  };
}

/** Quote text for display: page-break markers become ellipses, stray wrapping quote marks go. */
export function displayQuote(text: string): string {
  return text
    .replace(/\[\[PAGE_BREAK\]\]/g, " … ")
    .trim()
    .replace(/^["“”]+(?=["“])/, "")
    .replace(/(?<=["”])["“”]+$/, "");
}

// ── text fallback helpers ─────────────────────────────────────────────────────

type Span = { before: string; match: string; after: string };

function spanAt(text: string, start: number, length: number): Span {
  const end = Math.min(text.length, start + length);
  return { before: text.slice(0, start), match: text.slice(start, end), after: text.slice(end) };
}

/** Find the cited quote inside extracted document text, allowing uneven spacing. */
export function locateQuote(text: string, quote: string): Span | null {
  const needle = quote.replace(/\[\[PAGE_BREAK\]\]/g, " ").trim();
  if (!needle || !text) return null;

  const exact = text.indexOf(needle);
  if (exact >= 0) return spanAt(text, exact, needle.length);

  const lowerText = text.toLowerCase();
  const folded = lowerText.indexOf(needle.toLowerCase());
  if (folded >= 0) return spanAt(text, folded, needle.length);

  const words = needle.split(/\s+/).filter((word) => word.length > 1).slice(0, 10);
  if (!words.length) return null;
  const first = lowerText.indexOf(words[0].toLowerCase());
  if (first < 0) return null;

  let cursor = first;
  let end = first + words[0].length;
  for (const word of words) {
    const at = lowerText.indexOf(word.toLowerCase(), cursor);
    if (at < 0 || at - cursor > 500) break;
    end = at + word.length;
    cursor = end;
  }
  if (end <= first) return null;
  return spanAt(text, first, end - first);
}

type DocText = {
  document_id: string;
  title: string;
  text: string;
  pages?: { page: number; text: string }[];
};

// ── panel ─────────────────────────────────────────────────────────────────────

type Status = { tone: "ok" | "warn" | "muted"; text: string } | null;

/** `onClose` adds a close button; leave it out when the host provides its own. */
export function CitationDocumentPanel({ source, onClose }: { source: PanelSource; onClose?: () => void }) {
  const { documentId, quotes } = source;
  const [active, setActive] = useState(source.startAt ?? 0);
  const [view, setView] = useState<"pages" | "text">("pages");
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [jump, setJump] = useState(0);
  const [quoteOpen, setQuoteOpen] = useState(false);
  // The page in view and the page count, so the reader can move page to page (both views).
  const [page, setPage] = useState(1);
  const [total, setTotal] = useState<number | null>(null);
  const [pageJump, setPageJump] = useState<ViewerTarget | null>(null);
  // The current version: when the Assistant changes the document (or a change is undone) the panel shows the new text.
  const detail = useDocument(source.generated ? "" : documentId, { lean: true });
  const versionId = detail.data?.current_version_id ?? undefined;

  useEffect(() => {
    setActive(source.startAt ?? 0);
    setPage(source.quotes[source.startAt ?? 0]?.page ?? 1);
    setPageJump(null);
    setUnavailable(null);
    setView("pages");
    setStatus(null);
    setJump((n) => n + 1);
    setQuoteOpen(false);
  }, [source.nonce, source.startAt, documentId]);

  const quote = quotes[active] ?? null;
  const quoteTarget: ViewerTarget | null = useMemo(
    () => (quote ? { page: quote.page, quote: quote.quote, nonce: source.nonce * 1000 + active * 10 + jump } : null),
    [quote, source.nonce, active, jump],
  );
  const target = pageJump && (!quoteTarget || pageJump.nonce > quoteTarget.nonce) ? pageJump : quoteTarget;
  const goTo = (n: number) => {
    const last = total ?? n;
    const next = Math.min(Math.max(1, Math.floor(n)), Math.max(1, last));
    setPage(next);
    setPageJump({ page: next, quote: "", nonce: Date.now() * 10 });
  };
  const versionQuery = versionId ? `&version_id=${encodeURIComponent(versionId)}` : "";

  const onLocate = (r: LocateResult) => {
    if (r.found) setStatus({ tone: "ok", text: `Highlighted on page ${r.page}${r.exact ? "" : " (closest match)"}.` });
    else setStatus({ tone: "warn", text: r.page ? `These words were not found in the page text. Showing page ${r.page}.` : "These words were not found in the page text." });
  };

  const download = async () => {
    const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/download`, { headers: authHeaders() });
    if (!res.ok) return;
    const url = URL.createObjectURL(await res.blob());
    const a = document.createElement("a");
    a.href = url;
    a.download = source.title ?? documentId;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
  };

  return (
    <aside className="flex h-full min-h-0 flex-col bg-card" data-testid="citation-document-panel">
      <header className="flex items-start justify-between gap-3 border-b border-border px-3 py-2.5">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            <FileText className="h-3.5 w-3.5 text-muted-foreground" />
            {source.label}
            <span className="font-mono normal-case" data-testid="panel-page-current">· page {page}{total ? ` of ${total}` : ""}</span>
          </div>
          <h2 className="mt-0.5 truncate font-display text-sm font-normal text-ink" title={source.title ?? documentId}>
            {source.title ?? documentId}
          </h2>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton label="Download original" onClick={() => void download()}>
            <Download className="h-4 w-4" />
          </IconButton>
          {!source.generated && (
            <Link
              to={`/documents/${encodeURIComponent(documentId)}?page=${page}`}
              title="Open in document workspace"
              className="mr-1 inline-flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs font-medium text-foreground hover:bg-secondary"
            >
              <ExternalLink className="h-3.5 w-3.5" />
              Open in workspace
            </Link>
          )}
          {onClose && (
            <IconButton label="Close document" onClick={onClose}>
              <X className="h-4 w-4" />
            </IconButton>
          )}
        </div>
      </header>

      {quote && (
        <div className="space-y-1.5 border-b border-border px-3 py-2">
          <div className="flex items-center gap-2">
            <blockquote
              className={cn(
                "flex-1 cursor-pointer border-l-2 border-warning/60 pl-2 text-[12px] italic text-muted-foreground",
                !quoteOpen && "line-clamp-2",
              )}
              title={quoteOpen ? "Show less" : "Show the whole quote"}
              onClick={() => setQuoteOpen((v) => !v)}
              data-testid="panel-quote"
            >
              {displayQuote(quote.quote)}
            </blockquote>
            {quotes.length > 1 && (
              <div className="flex shrink-0 items-center gap-0.5 text-xs text-muted-foreground" data-testid="panel-quote-switcher">
                <IconButton label="Previous quote" disabled={active === 0} onClick={() => setActive((i) => i - 1)}>
                  <ChevronLeft className="h-3.5 w-3.5" />
                </IconButton>
                <span className="font-mono">
                  {active + 1}/{quotes.length}
                </span>
                <IconButton label="Next quote" disabled={active >= quotes.length - 1} onClick={() => setActive((i) => i + 1)}>
                  <ChevronRight className="h-3.5 w-3.5" />
                </IconButton>
              </div>
            )}
          </div>
          {quote.verified === false && (
            <p className="flex items-center gap-1 text-xs font-medium text-warning-ink" data-testid="panel-unverified">
              <AlertTriangle className="h-3.5 w-3.5" />
              Not confirmed: this quote was not found word-for-word in the document text.
            </p>
          )}
          {status && (
            <p
              className={cn(
                "flex items-center gap-1 text-xs",
                status.tone === "ok" ? "text-success-ink" : "text-muted-foreground",
              )}
              data-testid="panel-locate-status"
            >
              {status.tone === "ok" ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
              {status.text}
            </p>
          )}
        </div>
      )}

      {unavailable ? (
        <p className="border-b border-border px-3 py-1.5 text-xs text-muted-foreground" data-testid="panel-text-only">
          Page view isn't available for this file. Showing its text.
        </p>
      ) : (
      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
        {(["pages", "text"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            data-testid={`panel-view-${v}`}
            className={cn(
              "rounded-md px-2 py-0.5 text-xs disabled:opacity-40",
              view === v ? "bg-secondary font-medium text-ink" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {v === "pages" ? "Pages" : "Text"}
          </button>
        ))}
        <PageNav page={page} total={total} onGo={goTo} />
      </div>
      )}
      {unavailable && <div className="flex justify-end border-b border-border px-3 py-1"><PageNav page={page} total={total} onGo={goTo} /></div>}

      <div className="min-h-0 flex-1">
        {view === "pages" && !unavailable ? (
          <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading the viewer…</p>}>
          <DocumentViewer
            key={versionId ?? "current"}
            src={`/api/documents/${encodeURIComponent(documentId)}/render?view=final${versionQuery}`}
            wordsUrl={(n) => `/api/documents/${encodeURIComponent(documentId)}/pages/${n}/words?view=final${versionQuery}`}
            target={target}
            startPage={page}
            onPageChange={setPage}
            onDocument={setTotal}
            onLocate={onLocate}
            onUnavailable={(reason) => {
              setUnavailable(reason);
              setView("text");
            }}
          />
          </Suspense>
        ) : (
          <TextView documentId={documentId} quote={quote} versionId={versionId} page={page} pageJump={pageJump?.nonce ?? 0}
            onPages={setTotal} onPage={setPage} />
        )}
      </div>
    </aside>
  );
}

/** Page controls for the panel: previous / next and a page box, with the page in view. */
function PageNav({ page, total, onGo }: { page: number; total: number | null; onGo: (n: number) => void }) {
  const [draft, setDraft] = useState(String(page));
  useEffect(() => setDraft(String(page)), [page]);
  return (
    <div className="ml-auto flex items-center gap-1 text-xs text-muted-foreground" data-testid="panel-page-nav">
      <button type="button" aria-label="Previous page" disabled={page <= 1} onClick={() => onGo(page - 1)}
        className="rounded-md border border-border p-1 hover:bg-secondary disabled:opacity-30" data-testid="panel-page-prev">
        <ChevronLeft className="h-3.5 w-3.5" />
      </button>
      <span>Page</span>
      <input
        value={draft}
        onChange={(e) => setDraft(e.target.value.replace(/[^0-9]/g, ""))}
        onKeyDown={(e) => { if (e.key === "Enter") onGo(Number(draft) || page); }}
        onBlur={() => setDraft(String(page))}
        aria-label="Page number"
        inputMode="numeric"
        data-testid="panel-page-input"
        className="w-9 rounded border border-border bg-background px-1 py-0.5 text-center font-mono text-foreground"
      />
      <span data-testid="panel-page-total">of {total ?? "…"}</span>
      <button type="button" aria-label="Next page" disabled={total !== null && page >= total} onClick={() => onGo(page + 1)}
        className="rounded-md border border-border p-1 hover:bg-secondary disabled:opacity-30" data-testid="panel-page-next">
        <ChevronRight className="h-3.5 w-3.5" />
      </button>
    </div>
  );
}

function IconButton({
  label,
  onClick,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground disabled:opacity-30"
    >
      {children}
    </button>
  );
}

// ── text view: extracted text by page, with the quote marked ──────────────────

function TextView({ documentId, quote, versionId, page, pageJump, onPages, onPage }: {
  documentId: string;
  quote: SourceQuote | null;
  versionId?: string;
  page: number;
  /** Changes when the reader asks for a page (the page buttons). */
  pageJump: number;
  onPages: (n: number) => void;
  onPage: (n: number) => void;
}) {
  const [doc, setDoc] = useState<DocText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);
  const scrollRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    let cancelled = false;
    setDoc(null);
    setError(null);
    apiFetch<DocText>(`/api/documents/${encodeURIComponent(documentId)}/text`)
      .then((d) => !cancelled && setDoc(d))
      .catch((err: unknown) => !cancelled && setError(err instanceof Error ? err.message : "Could not open this document."));
    return () => {
      cancelled = true;
    };
  }, [documentId, versionId]);

  const pages = useMemo(() => {
    if (!doc) return [];
    return doc.pages?.length ? doc.pages : [{ page: 1, text: doc.text }];
  }, [doc]);
  useEffect(() => {
    if (pages.length) onPages(pages[pages.length - 1].page);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pages]);
  useEffect(() => {
    if (!pageJump) return;
    scrollRef.current?.querySelector(`[data-page="${page}"]`)?.scrollIntoView({ block: "start" });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [pageJump]);
  const onScroll = () => {
    const box = scrollRef.current;
    if (!box) return;
    const top = box.getBoundingClientRect().top;
    const cards = Array.from(box.querySelectorAll<HTMLElement>("[data-page]"));
    const seen = cards.find((c) => c.getBoundingClientRect().bottom > top + 40);
    if (seen) onPage(Number(seen.dataset.page));
  };

  // Mark the first page whose text contains the quote, preferring the cited page.
  const hit = useMemo(() => {
    if (!quote?.quote) return null;
    const ordered = [...pages].sort((a, b) => (a.page === quote.page ? -1 : b.page === quote.page ? 1 : a.page - b.page));
    for (const p of ordered) {
      const span = locateQuote(p.text, quote.quote);
      if (span) return { page: p.page, span };
    }
    return null;
  }, [pages, quote]);

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center" });
  }, [hit]);

  if (error) return <p className="p-4 text-sm text-destructive">{error}</p>;
  if (!doc) return <p className="p-4 text-sm text-muted-foreground">Loading the document text…</p>;
  if (pages.every((p) => !p.text?.trim())) {
    return (
      <p className="p-4 text-sm text-muted-foreground" data-testid="panel-no-text">
        No text has been extracted from this document yet. Download the original to read it.
      </p>
    );
  }

  return (
    <div ref={scrollRef} onScroll={onScroll} className="h-full overflow-y-auto bg-muted/40 px-4 py-4" data-testid="panel-text-view">
      {quote && !hit && (
        <p className="mb-3 text-xs text-muted-foreground">The quoted words were not found as a continuous passage.</p>
      )}
      <div className="mx-auto max-w-[70ch] space-y-3">
        {pages.map((p) => (
          <article key={p.page} data-page={p.page} className="rounded-md border border-border bg-background px-4 py-3 text-[13.5px] leading-[1.7] text-foreground/90">
            <div className="mb-1.5 font-mono text-xs uppercase tracking-wider text-muted-foreground">Page {p.page}</div>
            {hit?.page === p.page ? (
              <p className="whitespace-pre-wrap">
                {hit.span.before}
                <mark ref={markRef} data-testid="citation-highlight" className="rounded-sm bg-highlight px-0.5 text-ink">
                  {hit.span.match}
                </mark>
                {hit.span.after}
              </p>
            ) : (
              <p className="whitespace-pre-wrap">{p.text}</p>
            )}
          </article>
        ))}
      </div>
    </div>
  );
}
