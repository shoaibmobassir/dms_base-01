import { useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { GlobalWorkerOptions, TextLayer, getDocument, type PDFDocumentProxy } from "pdfjs-dist";
import workerUrl from "pdfjs-dist/build/pdf.worker.min.mjs?url";
import { ChevronDown, ChevronUp, Maximize, MoveHorizontal, ZoomIn, ZoomOut } from "lucide-react";
import { authHeaders } from "@/api/client";
import { cn } from "@/lib/utils";
import { findQuoteInRuns, pageSearchOrder } from "./findQuote";
import "./viewer.css";

GlobalWorkerOptions.workerSrc = workerUrl;

// Decoders for scanned images (JPEG 2000, JBIG2), fonts and character maps; copied to public/ by scripts/copy-pdfjs-assets.mjs.
const ASSETS = `${import.meta.env.BASE_URL}pdfjs/`;
const DOCUMENT_OPTIONS = {
  wasmUrl: `${ASSETS}wasm/`,
  standardFontDataUrl: `${ASSETS}standard_fonts/`,
  cMapUrl: `${ASSETS}cmaps/`,
  cMapPacked: true,
  iccUrl: `${ASSETS}iccs/`,
};
/** A page whose text layer holds fewer characters than this is treated as a scanned image. */
const SCANNED_TEXT_CHARS = 40;
/** OCR is slow, so only the cited page and its neighbours are read that way. */
const OCR_PAGE_LIMIT = 3;

/** Where to take the reader: a page, and optionally words to highlight on it. */
export type ViewerTarget = { page: number | null; quote: string; nonce: number };
export type LocateResult = { found: boolean; page: number | null; exact: boolean };

type Zoom = { mode: "fit-width" } | { mode: "fit-page" } | { mode: "custom"; scale: number };
type PageSize = { w: number; h: number };
type TextContent = Awaited<ReturnType<Awaited<ReturnType<PDFDocumentProxy["getPage"]>>["getTextContent"]>>;
/** Highlight box in page fractions (0..1), from OCR on scanned pages. */
type Box = { x0: number; y0: number; x1: number; y1: number };
type Highlight = { page: number; nonce: number; runs?: number[]; boxes?: Box[] };
type OcrWord = Box & { text: string; line: string };

/** Merge matched OCR words into one box per line. */
function lineBoxes(words: OcrWord[]): Box[] {
  const boxes: (Box & { line: string })[] = [];
  for (const w of words) {
    const last = boxes[boxes.length - 1];
    if (last && last.line === w.line) {
      last.x0 = Math.min(last.x0, w.x0);
      last.y0 = Math.min(last.y0, w.y0);
      last.x1 = Math.max(last.x1, w.x1);
      last.y1 = Math.max(last.y1, w.y1);
    } else {
      boxes.push({ ...w });
    }
  }
  return boxes.map(({ x0, y0, x1, y1 }) => ({ x0, y0, x1, y1 }));
}

const GAP = 12;
const PAD = 16;
const ZOOM_STEPS = [0.5, 0.67, 0.8, 0.9, 1, 1.1, 1.25, 1.5, 1.75, 2, 2.5, 3];

function runsOf(content: TextContent): string[] {
  return content.items.filter((item): item is { str: string } & typeof item => "str" in item).map((item) => item.str);
}

export function DocumentViewer({
  src,
  wordsUrl,
  target,
  onUnavailable,
  onLocate,
}: {
  src: string;
  /** OCR word boxes for one page; used when a page is a scanned image. */
  wordsUrl?: (page: number) => string;
  target?: ViewerTarget | null;
  onUnavailable?: (reason: string) => void;
  onLocate?: (result: LocateResult) => void;
}) {
  const scrollRef = useRef<HTMLDivElement>(null);
  const pageRefs = useRef<(HTMLDivElement | null)[]>([]);
  const textCache = useRef(new Map<number, Promise<TextContent>>());
  const anchor = useRef({ page: 1, fraction: 0 });
  const callbacks = useRef({ onUnavailable, onLocate, wordsUrl });
  callbacks.current = { onUnavailable, onLocate, wordsUrl };

  const [doc, setDoc] = useState<PDFDocumentProxy | null>(null);
  const [sizes, setSizes] = useState<PageSize[]>([]);
  const [status, setStatus] = useState<"loading" | "ready" | "error">("loading");
  const [error, setError] = useState("");
  const [zoom, setZoom] = useState<Zoom>({ mode: "fit-width" });
  const [box, setBox] = useState({ w: 0, h: 0 });
  const [current, setCurrent] = useState(1);
  const [pageInput, setPageInput] = useState("1");
  const [highlight, setHighlight] = useState<Highlight | null>(null);

  // Load the PDF and every page's natural size (placeholders keep the right height).
  useEffect(() => {
    let cancelled = false;
    let task: ReturnType<typeof getDocument> | null = null;
    setStatus("loading");
    setDoc(null);
    setSizes([]);
    setHighlight(null);
    textCache.current = new Map();
    (async () => {
      const res = await fetch(src, { headers: authHeaders() });
      if (res.status === 404) {
        // Text-only records (no stored original): the panel shows the extracted text instead.
        if (!cancelled) callbacks.current.onUnavailable?.("No original file is stored for this document.");
        return;
      }
      if (res.status === 415) {
        let reason = "This file cannot be shown as pages.";
        try {
          reason = ((await res.json()) as { detail?: string }).detail ?? reason;
        } catch {
          // keep default
        }
        if (!cancelled) callbacks.current.onUnavailable?.(reason);
        return;
      }
      if (!res.ok) throw new Error(`Could not load the file (${res.status}).`);
      const data = new Uint8Array(await res.arrayBuffer());
      task = getDocument({ data, ...DOCUMENT_OPTIONS });
      const pdf = await task.promise;
      if (cancelled) return;
      const natural = await Promise.all(
        Array.from({ length: pdf.numPages }, async (_, i) => {
          const page = await pdf.getPage(i + 1);
          const v = page.getViewport({ scale: 1 });
          return { w: v.width, h: v.height };
        }),
      );
      if (cancelled) return;
      pageRefs.current = [];
      setSizes(natural);
      setDoc(pdf);
      setCurrent(1);
      setPageInput("1");
      setStatus("ready");
    })().catch((err: unknown) => {
      if (cancelled) return;
      setError(err instanceof Error ? err.message : "Could not open this document.");
      setStatus("error");
    });
    return () => {
      cancelled = true;
      void task?.destroy();
    };
  }, [src]);

  // Track the panel size so "fit width" follows the divider.
  useEffect(() => {
    const el = scrollRef.current;
    if (!el) return;
    const observer = new ResizeObserver(() => setBox({ w: el.clientWidth, h: el.clientHeight }));
    observer.observe(el);
    return () => observer.disconnect();
  }, []);

  const base = sizes[0];
  const fitWidth = base && box.w ? Math.max(0.2, (box.w - PAD * 2) / base.w) : 1;
  const fitPage = base && box.h ? Math.min(fitWidth, (box.h - PAD * 2) / base.h) : 1;
  const scale = zoom.mode === "fit-width" ? fitWidth : zoom.mode === "fit-page" ? fitPage : zoom.scale;

  const getText = useCallback(
    (number: number) => {
      if (!doc) return Promise.reject(new Error("no document"));
      let pending = textCache.current.get(number);
      if (!pending) {
        pending = doc.getPage(number).then((page) => page.getTextContent());
        textCache.current.set(number, pending);
      }
      return pending;
    },
    [doc],
  );

  const goToPage = useCallback((n: number, behavior: ScrollBehavior = "auto") => {
    const el = scrollRef.current;
    const pageEl = pageRefs.current[n - 1];
    if (!el || !pageEl) return;
    el.scrollTo({ top: pageEl.offsetTop - GAP, behavior });
  }, []);

  // Keep the reader's place when the zoom changes.
  useLayoutEffect(() => {
    const el = scrollRef.current;
    const pageEl = pageRefs.current[anchor.current.page - 1];
    if (!el || !pageEl) return;
    el.scrollTop = pageEl.offsetTop + anchor.current.fraction * pageEl.offsetHeight - GAP;
  }, [scale]);

  const onScroll = () => {
    const el = scrollRef.current;
    if (!el) return;
    const probe = el.scrollTop + el.clientHeight * 0.3;
    let page = 1;
    for (let i = 0; i < pageRefs.current.length; i++) {
      const p = pageRefs.current[i];
      if (p && p.offsetTop <= probe) page = i + 1;
      else break;
    }
    const pageEl = pageRefs.current[page - 1];
    const top = el.scrollTop + GAP;
    anchor.current = {
      page,
      fraction: pageEl ? Math.min(1, Math.max(0, (top - pageEl.offsetTop) / pageEl.offsetHeight)) : 0,
    };
    if (page !== current) {
      setCurrent(page);
      setPageInput(String(page));
    }
  };

  // Jump to a citation: search the cited page first, then its neighbours, then all pages.
  useEffect(() => {
    if (!doc || !target) return;
    let cancelled = false;
    (async () => {
      if (!target.quote.trim()) {
        if (target.page) goToPage(Math.min(target.page, doc.numPages));
        callbacks.current.onLocate?.({ found: false, page: target.page, exact: false });
        return;
      }
      let ocrPages = 0;
      for (const number of pageSearchOrder(target.page, doc.numPages)) {
        const runs = runsOf(await getText(number));
        if (cancelled) return;
        const match = findQuoteInRuns(runs, target.quote);
        if (match) {
          setHighlight({ page: number, runs: match.runs, nonce: target.nonce });
          goToPage(number);
          callbacks.current.onLocate?.({ found: true, page: number, exact: match.exact });
          return;
        }
        // Scanned page: read word positions with OCR and match against those.
        const url = callbacks.current.wordsUrl?.(number);
        if (url && runs.join("").trim().length < SCANNED_TEXT_CHARS && ocrPages < OCR_PAGE_LIMIT) {
          ocrPages += 1;
          if (ocrPages === 1) goToPage(number);
          const res = await fetch(url, { headers: authHeaders() });
          if (cancelled) return;
          if (!res.ok) continue;
          const words = ((await res.json()) as { words: OcrWord[] }).words;
          const hit = findQuoteInRuns(words.map((w) => w.text), target.quote);
          if (cancelled) return;
          if (hit) {
            setHighlight({ page: number, boxes: lineBoxes(hit.runs.map((i) => words[i])), nonce: target.nonce });
            goToPage(number);
            callbacks.current.onLocate?.({ found: true, page: number, exact: hit.exact });
            return;
          }
        }
      }
      setHighlight(null);
      if (target.page) goToPage(Math.min(target.page, doc.numPages));
      callbacks.current.onLocate?.({ found: false, page: target.page, exact: false });
    })().catch(() => undefined);
    return () => {
      cancelled = true;
    };
    // target.nonce changes on every citation click, including repeat clicks.
  }, [doc, target?.nonce, getText, goToPage]);

  const centreOn = useCallback((el: HTMLElement) => {
    const scroller = scrollRef.current;
    if (!scroller) return;
    const a = el.getBoundingClientRect();
    const b = scroller.getBoundingClientRect();
    scroller.scrollTo({ top: scroller.scrollTop + a.top - b.top - scroller.clientHeight / 2 + a.height / 2 });
  }, []);

  const pageCount = doc?.numPages ?? 0;
  const step = (dir: 1 | -1) => {
    const next = [...ZOOM_STEPS].sort((x, y) => (dir === 1 ? x - y : y - x)).find((s) => (dir === 1 ? s > scale + 0.01 : s < scale - 0.01));
    if (next) setZoom({ mode: "custom", scale: next });
  };
  const commitPageInput = () => {
    const n = Number.parseInt(pageInput, 10);
    if (Number.isFinite(n) && n >= 1 && n <= pageCount) goToPage(n);
    else setPageInput(String(current));
  };

  const onKeyDown = (e: React.KeyboardEvent) => {
    if ((e.target as HTMLElement).tagName === "INPUT") return;
    if (e.key === "PageDown" || (e.key === "ArrowRight" && !e.metaKey)) {
      e.preventDefault();
      goToPage(Math.min(pageCount, current + 1));
    } else if (e.key === "PageUp" || (e.key === "ArrowLeft" && !e.metaKey)) {
      e.preventDefault();
      goToPage(Math.max(1, current - 1));
    } else if ((e.ctrlKey || e.metaKey) && (e.key === "=" || e.key === "+")) {
      e.preventDefault();
      step(1);
    } else if ((e.ctrlKey || e.metaKey) && e.key === "-") {
      e.preventDefault();
      step(-1);
    }
  };

  return (
    <div className="flex h-full min-h-0 flex-col outline-none" tabIndex={0} onKeyDown={onKeyDown} data-testid="document-viewer">
      <div className="flex flex-wrap items-center gap-1 border-b border-border bg-card px-2 py-1.5 text-xs">
        <ToolButton label="Previous page" disabled={current <= 1} onClick={() => goToPage(current - 1)} testId="viewer-prev">
          <ChevronUp className="h-4 w-4" />
        </ToolButton>
        <ToolButton label="Next page" disabled={!pageCount || current >= pageCount} onClick={() => goToPage(current + 1)} testId="viewer-next">
          <ChevronDown className="h-4 w-4" />
        </ToolButton>
        <label className="ml-1 flex items-center gap-1 text-muted-foreground">
          <span className="sr-only">Page</span>
          <input
            value={pageInput}
            onChange={(e) => setPageInput(e.target.value.replace(/\D/g, ""))}
            onKeyDown={(e) => e.key === "Enter" && commitPageInput()}
            onBlur={commitPageInput}
            inputMode="numeric"
            aria-label="Page number"
            data-testid="viewer-page-input"
            className="w-10 rounded border border-border bg-background px-1 py-0.5 text-center font-mono text-xs text-foreground"
          />
          <span className="font-mono" data-testid="viewer-page-count">/ {pageCount || "–"}</span>
        </label>
        <div className="mx-1 h-4 w-px bg-border" />
        <ToolButton label="Zoom out" onClick={() => step(-1)} testId="viewer-zoom-out">
          <ZoomOut className="h-4 w-4" />
        </ToolButton>
        <span className="w-11 text-center font-mono text-muted-foreground" data-testid="viewer-zoom">
          {Math.round(scale * 100)}%
        </span>
        <ToolButton label="Zoom in" onClick={() => step(1)} testId="viewer-zoom-in">
          <ZoomIn className="h-4 w-4" />
        </ToolButton>
        <ToolButton label="Fit width" active={zoom.mode === "fit-width"} onClick={() => setZoom({ mode: "fit-width" })} testId="viewer-fit-width">
          <MoveHorizontal className="h-4 w-4" />
        </ToolButton>
        <ToolButton label="Fit page" active={zoom.mode === "fit-page"} onClick={() => setZoom({ mode: "fit-page" })} testId="viewer-fit-page">
          <Maximize className="h-4 w-4" />
        </ToolButton>
      </div>

      <div ref={scrollRef} onScroll={onScroll} className="relative min-h-0 flex-1 overflow-auto bg-muted/60" data-testid="viewer-scroll">
        {status === "loading" && <p className="p-6 text-sm text-muted-foreground">Loading the document…</p>}
        {status === "error" && <p className="p-6 text-sm text-destructive">{error}</p>}
        {doc && (
          <div className="flex flex-col items-center" style={{ padding: `${GAP}px ${PAD}px`, gap: GAP }}>
            {sizes.map((size, i) => (
              <PdfPage
                key={i}
                ref={(el) => {
                  pageRefs.current[i] = el;
                }}
                doc={doc}
                number={i + 1}
                size={size}
                scale={scale}
                root={scrollRef}
                getText={getText}
                highlight={highlight?.page === i + 1 ? highlight : null}
                onHighlightShown={centreOn}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

function ToolButton({
  label,
  onClick,
  disabled,
  active,
  testId,
  children,
}: {
  label: string;
  onClick: () => void;
  disabled?: boolean;
  active?: boolean;
  testId?: string;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      title={label}
      aria-label={label}
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className={cn(
        "rounded p-1 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground disabled:opacity-30",
        active && "bg-secondary text-foreground",
      )}
    >
      {children}
    </button>
  );
}

// ── one page: canvas + selectable text layer, rendered only near the viewport ──

type PdfPageProps = {
  doc: PDFDocumentProxy;
  number: number;
  size: PageSize;
  scale: number;
  root: React.RefObject<HTMLDivElement | null>;
  getText: (n: number) => Promise<TextContent>;
  highlight: Highlight | null;
  onHighlightShown: (el: HTMLElement) => void;
  ref?: React.Ref<HTMLDivElement>;
};

function PdfPage({ doc, number, size, scale, root, getText, highlight, onHighlightShown, ref }: PdfPageProps) {
  const wrapRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const textRef = useRef<HTMLDivElement>(null);
  const shownNonce = useRef<number | null>(null);
  const [near, setNear] = useState(false);
  const [textDivs, setTextDivs] = useState<HTMLElement[]>([]);

  useEffect(() => {
    const el = wrapRef.current;
    if (!el) return;
    const observer = new IntersectionObserver(([entry]) => setNear(entry.isIntersecting), {
      root: root.current,
      rootMargin: "900px 0px",
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [root]);

  useEffect(() => {
    const canvas = canvasRef.current;
    const textEl = textRef.current;
    if (!near || !canvas || !textEl) return;
    let cancelled = false;
    let renderTask: { cancel: () => void; promise: Promise<unknown> } | null = null;
    let textLayer: TextLayer | null = null;
    (async () => {
      const page = await doc.getPage(number);
      if (cancelled) return;
      const viewport = page.getViewport({ scale });
      const ratio = window.devicePixelRatio || 1;
      canvas.width = Math.floor(viewport.width * ratio);
      canvas.height = Math.floor(viewport.height * ratio);
      renderTask = page.render({
        canvas,
        viewport,
        transform: ratio !== 1 ? [ratio, 0, 0, ratio, 0, 0] : undefined,
      });
      await renderTask.promise;
      if (cancelled) return;
      const content = await getText(number);
      if (cancelled) return;
      textEl.replaceChildren();
      textLayer = new TextLayer({ textContentSource: content, container: textEl, viewport });
      await textLayer.render();
      if (!cancelled) setTextDivs([...textLayer.textDivs]);
    })().catch(() => undefined); // cancelled renders reject; nothing to show
    return () => {
      cancelled = true;
      renderTask?.cancel();
      textLayer?.cancel();
    };
  }, [near, doc, number, scale, getText]);

  const boxRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!highlight?.boxes?.length || !boxRef.current || shownNonce.current === highlight.nonce) return;
    shownNonce.current = highlight.nonce;
    onHighlightShown(boxRef.current);
  }, [highlight, onHighlightShown]);

  useEffect(() => {
    for (const div of textDivs) div.classList.remove("viewer-highlight");
    if (!highlight?.runs || !textDivs.length) return;
    const marked = highlight.runs.map((i) => textDivs[i]).filter(Boolean);
    for (const div of marked) div.classList.add("viewer-highlight");
    if (marked[0] && shownNonce.current !== highlight.nonce) {
      shownNonce.current = highlight.nonce;
      onHighlightShown(marked[0]);
    }
  }, [highlight, textDivs, onHighlightShown]);

  const width = Math.floor(size.w * scale);
  const height = Math.floor(size.h * scale);
  return (
    <div
      ref={(el) => {
        wrapRef.current = el;
        if (typeof ref === "function") ref(el);
        else if (ref) (ref as React.MutableRefObject<HTMLDivElement | null>).current = el;
      }}
      className="viewer-page relative shrink-0 bg-white shadow-sm ring-1 ring-black/5"
      style={{ width, height, ["--total-scale-factor" as string]: scale, ["--scale-factor" as string]: scale }}
      data-testid="viewer-page"
      data-page={number}
    >
      <canvas ref={canvasRef} className="absolute inset-0" style={{ width, height }} />
      <div ref={textRef} className="textLayer" data-highlighted={highlight ? "true" : undefined} />
      {highlight?.boxes?.map((b, i) => (
        <div
          key={i}
          ref={i === 0 ? boxRef : undefined}
          className="viewer-highlight-box"
          data-testid="viewer-ocr-highlight"
          style={{
            left: `${b.x0 * 100}%`,
            top: `${b.y0 * 100}%`,
            width: `${(b.x1 - b.x0) * 100}%`,
            height: `${(b.y1 - b.y0) * 100}%`,
          }}
        />
      ))}
    </div>
  );
}
