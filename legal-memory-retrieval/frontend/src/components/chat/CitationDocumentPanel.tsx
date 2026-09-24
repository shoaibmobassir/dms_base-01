import { useEffect, useMemo, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { FileText, X } from "lucide-react";
import { apiFetch, authHeaders } from "@/api/client";
import type { Citation } from "@/api/types";

type DocText = {
  document_id: string;
  title: string;
  text: string;
  chunk_count: number;
};

type Span = { before: string; match: string; after: string };

const WINDOW = 900;

function spanAt(text: string, start: number, length: number): Span {
  const end = Math.min(text.length, start + length);
  return { before: text.slice(0, start), match: text.slice(start, end), after: text.slice(end) };
}

/** Find the cited quote inside the extracted document text, allowing uneven spacing. */
export function locateQuote(text: string, quote: string): Span | null {
  const needle = quote.trim();
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

function windowed(span: Span, expanded: boolean): Span {
  if (expanded) return span;
  return {
    before: span.before.length > WINDOW ? `…${span.before.slice(-WINDOW)}` : span.before,
    match: span.match,
    after: span.after.length > WINDOW ? `${span.after.slice(0, WINDOW)}…` : span.after,
  };
}

function quoteOf(citation: Citation): string {
  if (typeof citation.quote === "string" && citation.quote.trim()) return citation.quote;
  const quotes = citation.quotes;
  if (Array.isArray(quotes) && quotes.length > 0) {
    const first = quotes[0] as { quote?: string };
    if (typeof first?.quote === "string") return first.quote;
  }
  if (typeof citation.snippet === "string") return citation.snippet;
  return "";
}

function pageOf(citation: Citation): string | null {
  if (citation.page != null && citation.page !== "") return String(citation.page);
  const quotes = citation.quotes;
  if (Array.isArray(quotes) && quotes.length > 0) {
    const page = (quotes[0] as { page?: string | number }).page;
    if (page != null && page !== "") return String(page);
  }
  return null;
}

export function CitationDocumentPanel({
  citation,
  onClose,
}: {
  citation: Citation;
  onClose: () => void;
}) {
  const documentId = String(citation.document_id ?? "");
  const quote = quoteOf(citation);
  const page = pageOf(citation);
  const markRef = useRef<HTMLElement>(null);
  const [doc, setDoc] = useState<DocText | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState(false);
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [view, setView] = useState<"passage" | "file">("passage");

  useEffect(() => {
    if (!documentId) return;
    let cancelled = false;
    setDoc(null);
    setError(null);
    setExpanded(false);
    setView("passage");
    apiFetch<DocText>(`/api/documents/${encodeURIComponent(documentId)}/text`)
      .then((d) => {
        if (!cancelled) setDoc(d);
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : "Could not open this document.");
      });
    return () => {
      cancelled = true;
    };
  }, [documentId]);

  useEffect(() => {
    return () => {
      if (pdfUrl) URL.revokeObjectURL(pdfUrl);
    };
  }, [pdfUrl]);

  const span = useMemo(() => (doc ? locateQuote(doc.text, quote) : null), [doc, quote]);

  useEffect(() => {
    markRef.current?.scrollIntoView({ block: "center" });
  }, [span, expanded, view]);

  const openFile = async () => {
    setView("file");
    if (pdfUrl || !documentId) return;
    const res = await fetch(`/api/documents/${encodeURIComponent(documentId)}/download`, {
      headers: authHeaders(),
    });
    if (!res.ok) {
      setError("The original file is not available.");
      return;
    }
    const blob = await res.blob();
    setPdfUrl(URL.createObjectURL(blob));
  };

  const shown = span ? windowed(span, expanded) : null;
  const verified = citation.verified === true;

  return (
    <aside
      className="absolute right-0 top-0 bottom-0 z-40 flex w-[min(560px,100%)] flex-col border-l border-border bg-card shadow-xl"
      data-testid="citation-document-panel"
    >
      <header className="flex items-start justify-between gap-3 border-b border-border px-4 py-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
            <FileText className="h-3.5 w-3.5 text-amber-500" />
            Cited passage
            {page && <span className="font-mono normal-case">· page {page}</span>}
          </div>
          <h2 className="mt-1 truncate font-display text-sm font-semibold text-ink">
            {String(citation.title ?? doc?.title ?? documentId)}
          </h2>
          <p className="mt-1 text-[11px] text-muted-foreground">
            {verified ? "Quote checked against the document text." : "Opening the source the answer cited."}
          </p>
        </div>
        <button type="button" onClick={onClose} aria-label="Close document" className="rounded p-1 text-muted-foreground hover:text-foreground">
          <X className="h-4 w-4" />
        </button>
      </header>

      <div className="flex items-center gap-2 border-b border-border px-4 py-2">
        <button
          type="button"
          onClick={() => setView("passage")}
          className={`rounded-md px-2 py-1 text-xs ${view === "passage" ? "bg-secondary font-medium text-ink" : "text-muted-foreground"}`}
        >
          Highlighted text
        </button>
        <button
          type="button"
          onClick={() => void openFile()}
          className={`rounded-md px-2 py-1 text-xs ${view === "file" ? "bg-secondary font-medium text-ink" : "text-muted-foreground"}`}
        >
          Original file
        </button>
        {documentId && (
          <Link
            to={`/documents/${encodeURIComponent(documentId)}`}
            className="ml-auto text-xs font-medium text-wine hover:underline"
          >
            Open workspace
          </Link>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-4 py-4">
        {error && <p className="text-sm text-destructive">{error}</p>}
        {!error && !doc && view === "passage" && (
          <p className="text-sm text-muted-foreground">Loading the cited document…</p>
        )}

        {view === "file" && (
          pdfUrl ? (
            <iframe title="Original document" src={pdfUrl} className="h-full min-h-[480px] w-full rounded-md border border-border bg-white" />
          ) : (
            <p className="text-sm text-muted-foreground">Loading the original file…</p>
          )
        )}

        {view === "passage" && doc && shown && (
          <article className="rounded-lg border border-border bg-background px-4 py-5 text-[14px] leading-[1.75] text-foreground/90">
            <p className="whitespace-pre-wrap">
              {shown.before}
              <mark
                ref={markRef}
                data-testid="citation-highlight"
                className="rounded-sm bg-amber-200/90 px-0.5 text-ink dark:bg-amber-500/40"
              >
                {shown.match}
              </mark>
              {shown.after}
            </p>
            {(span && (span.before.length > WINDOW || span.after.length > WINDOW)) && (
              <button
                type="button"
                onClick={() => setExpanded((v) => !v)}
                className="mt-4 text-xs font-medium text-wine hover:underline"
              >
                {expanded ? "Show the cited passage" : "Show the full document text"}
              </button>
            )}
          </article>
        )}

        {view === "passage" && doc && !shown && (
          <div className="space-y-3">
            <p className="text-sm text-muted-foreground">
              The quoted words were not found as a continuous passage. The document text is below.
            </p>
            {quote && (
              <blockquote className="border-l-2 border-amber-500/70 pl-3 text-sm italic text-muted-foreground">
                {quote}
              </blockquote>
            )}
            <article className="whitespace-pre-wrap rounded-lg border border-border bg-background px-4 py-5 text-[14px] leading-[1.75]">
              {expanded ? doc.text : `${doc.text.slice(0, 2400)}${doc.text.length > 2400 ? "…" : ""}`}
            </article>
            {doc.text.length > 2400 && (
              <button type="button" onClick={() => setExpanded((v) => !v)} className="text-xs font-medium text-wine hover:underline">
                {expanded ? "Show less" : "Show the full document text"}
              </button>
            )}
          </div>
        )}
      </div>
    </aside>
  );
}
