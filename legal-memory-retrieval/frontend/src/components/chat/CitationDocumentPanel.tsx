import { Suspense, lazy, useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, CheckCircle2, ChevronLeft, ChevronRight, Download, ExternalLink, FileText, X } from "lucide-react";
import { apiFetch, authHeaders } from "@/api/client";
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

export function CitationDocumentPanel({ source, onClose }: { source: PanelSource; onClose: () => void }) {
  const { documentId, quotes } = source;
  const [active, setActive] = useState(source.startAt ?? 0);
  const [view, setView] = useState<"pages" | "text">("pages");
  const [unavailable, setUnavailable] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [jump, setJump] = useState(0);

  useEffect(() => {
    setActive(source.startAt ?? 0);
    setUnavailable(null);
    setView("pages");
    setStatus(null);
    setJump((n) => n + 1);
  }, [source.nonce, source.startAt, documentId]);

  const quote = quotes[active] ?? null;
  const target: ViewerTarget | null = useMemo(
    () => (quote ? { page: quote.page, quote: quote.quote, nonce: source.nonce * 1000 + active * 10 + jump } : null),
    [quote, source.nonce, active, jump],
  );

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
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <FileText className="h-3.5 w-3.5 text-amber-500" />
            {source.label}
            {quote?.page && <span className="font-mono normal-case">· page {quote.page}</span>}
          </div>
          <h2 className="mt-0.5 truncate font-display text-sm font-semibold text-ink" title={source.title ?? documentId}>
            {source.title ?? documentId}
          </h2>
        </div>
        <div className="flex shrink-0 items-center gap-0.5">
          <IconButton label="Download original" onClick={() => void download()}>
            <Download className="h-4 w-4" />
          </IconButton>
          {!source.generated && (
            <Link
              to={`/documents/${encodeURIComponent(documentId)}`}
              title="Open in document workspace"
              aria-label="Open in document workspace"
              className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground"
            >
              <ExternalLink className="h-4 w-4" />
            </Link>
          )}
          <IconButton label="Close document" onClick={onClose}>
            <X className="h-4 w-4" />
          </IconButton>
        </div>
      </header>

      {quote && (
        <div className="space-y-1.5 border-b border-border px-3 py-2">
          <div className="flex items-center gap-2">
            <blockquote className="line-clamp-2 flex-1 border-l-2 border-amber-500/70 pl-2 text-[12px] italic text-muted-foreground" data-testid="panel-quote">
              {quote.quote.replace(/\[\[PAGE_BREAK\]\]/g, " … ")}
            </blockquote>
            {quotes.length > 1 && (
              <div className="flex shrink-0 items-center gap-0.5 text-[11px] text-muted-foreground" data-testid="panel-quote-switcher">
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
            <p className="flex items-center gap-1 text-[11px] font-medium text-amber-700 dark:text-amber-400" data-testid="panel-unverified">
              <AlertTriangle className="h-3.5 w-3.5" />
              Not confirmed: this quote was not found word-for-word in the document text.
            </p>
          )}
          {status && (
            <p
              className={cn(
                "flex items-center gap-1 text-[11px]",
                status.tone === "ok" ? "text-emerald-700 dark:text-emerald-400" : "text-muted-foreground",
              )}
              data-testid="panel-locate-status"
            >
              {status.tone === "ok" ? <CheckCircle2 className="h-3.5 w-3.5" /> : <AlertTriangle className="h-3.5 w-3.5" />}
              {status.text}
            </p>
          )}
        </div>
      )}

      <div className="flex items-center gap-1 border-b border-border px-3 py-1.5">
        {(["pages", "text"] as const).map((v) => (
          <button
            key={v}
            type="button"
            onClick={() => setView(v)}
            disabled={v === "pages" && !!unavailable}
            data-testid={`panel-view-${v}`}
            className={cn(
              "rounded-md px-2 py-0.5 text-xs disabled:opacity-40",
              view === v ? "bg-secondary font-medium text-ink" : "text-muted-foreground hover:text-foreground",
            )}
          >
            {v === "pages" ? "Pages" : "Text"}
          </button>
        ))}
        {unavailable && <span className="ml-2 truncate text-[11px] text-muted-foreground">{unavailable} Showing extracted text.</span>}
      </div>

      <div className="min-h-0 flex-1">
        {view === "pages" && !unavailable ? (
          <Suspense fallback={<p className="p-6 text-sm text-muted-foreground">Loading the viewer…</p>}>
          <DocumentViewer
            src={`/api/documents/${encodeURIComponent(documentId)}/render`}
            wordsUrl={(page) => `/api/documents/${encodeURIComponent(documentId)}/pages/${page}/words`}
            target={target}
            onLocate={onLocate}
            onUnavailable={(reason) => {
              setUnavailable(reason);
              setView("text");
            }}
          />
          </Suspense>
        ) : (
          <TextView documentId={documentId} quote={quote} />
        )}
      </div>
    </aside>
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

function TextView({ documentId, quote }: { documentId: string; quote: SourceQuote | null }) {
  const [doc, setDoc] = useState<DocText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const markRef = useRef<HTMLElement>(null);

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
  }, [documentId]);

  const pages = useMemo(() => {
    if (!doc) return [];
    return doc.pages?.length ? doc.pages : [{ page: 1, text: doc.text }];
  }, [doc]);

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

  return (
    <div className="h-full overflow-y-auto bg-muted/40 px-4 py-4" data-testid="panel-text-view">
      {quote && !hit && (
        <p className="mb-3 text-xs text-muted-foreground">The quoted words were not found as a continuous passage.</p>
      )}
      <div className="mx-auto max-w-[70ch] space-y-3">
        {pages.map((p) => (
          <article key={p.page} className="rounded-md border border-border bg-background px-4 py-3 text-[13.5px] leading-[1.7] text-foreground/90">
            <div className="mb-1.5 font-mono text-[10px] uppercase tracking-wider text-muted-foreground">Page {p.page}</div>
            {hit?.page === p.page ? (
              <p className="whitespace-pre-wrap">
                {hit.span.before}
                <mark ref={markRef} data-testid="citation-highlight" className="rounded-sm bg-amber-200/90 px-0.5 text-ink dark:bg-amber-500/40">
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
