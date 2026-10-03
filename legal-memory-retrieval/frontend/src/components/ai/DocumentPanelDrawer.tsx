import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { Citation } from "@/api/types";
import { CitationDocumentPanel, sourceFromCitation, type PanelSource } from "@/components/chat/CitationDocumentPanel";

/**
 * Opens cited documents in the same preview panel the Assistant uses (page view,
 * highlighted quote, quote switcher). Like the Assistant, the page and the panel
 * sit side by side: the page narrows instead of being covered. On small screens
 * the panel takes the whole frame.
 */
type DocumentPanelValue = {
  isOpen: boolean;
  openCitation: (c: Citation) => void;
  openDocument: (documentId: string, opts?: { title?: string; snippet?: string }) => void;
  close: () => void;
};

const DocumentPanelContext = createContext<DocumentPanelValue | null>(null);

export function useDocumentPanel() {
  return useContext(DocumentPanelContext);
}

const WIDTH_KEY = "ask.panelWidth";
const MIN_WIDTH = 380;
// Room the page keeps beside the panel.
const MIN_PAGE = 520;

export function DocumentPanelProvider({ children }: { children: ReactNode }) {
  const [source, setSource] = useState<PanelSource | null>(null);
  const nonceRef = useRef(0);

  const show = useCallback((next: Omit<PanelSource, "nonce"> | null) => {
    if (next) setSource({ ...next, nonce: ++nonceRef.current });
  }, []);
  const openCitation = useCallback((c: Citation) => show(sourceFromCitation(c, 0)), [show]);
  const openDocument = useCallback(
    (documentId: string, opts?: { title?: string; snippet?: string }) =>
      show({
        documentId,
        title: opts?.title,
        label: "Cited source",
        quotes: opts?.snippet ? [{ page: null, quote: opts.snippet }] : [],
      }),
    [show],
  );
  const close = useCallback(() => setSource(null), []);
  const value = useMemo(() => ({ isOpen: !!source, openCitation, openDocument, close }), [source, openCitation, openDocument, close]);

  const frameRef = useRef<HTMLDivElement>(null);
  const clampWidth = useCallback((w: number) => {
    const total = frameRef.current?.clientWidth ?? window.innerWidth;
    return Math.round(Math.min(Math.max(w, MIN_WIDTH), Math.max(MIN_WIDTH, total - MIN_PAGE)));
  }, []);

  const [width, setWidth] = useState(() => {
    try {
      const saved = Number(window.localStorage.getItem(WIDTH_KEY));
      if (saved > 0) return saved;
    } catch {
      // storage unavailable
    }
    return Math.round(window.innerWidth * 0.4);
  });
  useEffect(() => {
    try {
      window.localStorage.setItem(WIDTH_KEY, String(width));
    } catch {
      // storage unavailable
    }
  }, [width]);

  useEffect(() => {
    if (!source) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && close();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [source, close]);

  const startResize = (e: React.PointerEvent<HTMLDivElement>) => {
    e.preventDefault();
    const handle = e.currentTarget;
    handle.setPointerCapture(e.pointerId);
    const right = frameRef.current?.getBoundingClientRect().right ?? window.innerWidth;
    const move = (ev: PointerEvent) => setWidth(clampWidth(right - ev.clientX));
    const stop = () => {
      handle.removeEventListener("pointermove", move);
      handle.removeEventListener("pointerup", stop);
      handle.removeEventListener("pointercancel", stop);
    };
    handle.addEventListener("pointermove", move);
    handle.addEventListener("pointerup", stop);
    handle.addEventListener("pointercancel", stop);
  };

  return (
    <DocumentPanelContext.Provider value={value}>
      <div ref={frameRef} className="relative flex h-full min-h-0 w-full overflow-hidden">
        <div className="min-h-0 min-w-0 flex-1 overflow-y-auto" data-testid="document-panel-page">
          {children}
        </div>
      {source && (
        <div
          className="absolute inset-0 z-40 flex bg-card lg:static lg:z-auto lg:w-[var(--panel-w)] lg:shrink-0"
          style={{ ["--panel-w" as string]: `${clampWidth(width)}px` }}
          data-testid="document-panel-drawer"
        >
          <div
            role="separator"
            aria-orientation="vertical"
            aria-label="Resize document panel"
            tabIndex={0}
            onPointerDown={startResize}
            onKeyDown={(e) => {
              if (e.key === "ArrowLeft") setWidth((w) => clampWidth(w + 32));
              if (e.key === "ArrowRight") setWidth((w) => clampWidth(w - 32));
            }}
            className="group relative hidden w-1.5 shrink-0 cursor-col-resize bg-border/70 transition-colors hover:bg-wine/40 focus-visible:bg-wine/50 focus-visible:outline-none lg:block"
          >
            <span className="absolute left-1/2 top-1/2 h-8 w-0.5 -translate-x-1/2 -translate-y-1/2 rounded bg-muted-foreground/40 group-hover:bg-wine" />
          </div>
          <div className="min-w-0 flex-1">
            <CitationDocumentPanel source={source} onClose={close} />
          </div>
        </div>
      )}
      </div>
    </DocumentPanelContext.Provider>
  );
}
