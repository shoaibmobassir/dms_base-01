import { useState } from "react";
import type { PanelSource } from "@/components/chat/CitationDocumentPanel";

export type ReviewCell = {
  question: string;
  answer: string;
  quote: string;
  page: number | null;
  verified: boolean;
  not_found: boolean;
  error?: string | null;
};

export type ReviewTableEvent = {
  type: "review_table";
  questions: string[];
  mode: "full" | "screen";
  stats?: { model_calls?: number; cached?: number; answered?: number; verified_quotes?: number; errors?: number };
  timings?: { total_ms?: number };
  rows: { document_id: string; title?: string | null; matter_code?: string | null; cells?: ReviewCell[]; relevance?: number[] }[];
};

const PAGE = 25;

/** The Assistant's multi-document review: one row per document, one column per question. */
export function ReviewTableCard({
  table,
  onOpen,
}: {
  table: ReviewTableEvent;
  onOpen: (source: Omit<PanelSource, "nonce">) => void;
}) {
  const [shown, setShown] = useState(PAGE);
  const [onlyAnswered, setOnlyAnswered] = useState(false);
  const full = table.mode !== "screen";
  const rows = onlyAnswered && full ? table.rows.filter((r) => r.cells?.some((c) => !c.not_found)) : table.rows;
  const secs = table.timings?.total_ms ? (table.timings.total_ms / 1000).toFixed(1) : null;

  return (
    <div className="mt-4 rounded-lg border border-border" data-testid="review-table">
      <div className="flex flex-wrap items-baseline justify-between gap-2 border-b border-border px-3 py-2">
        <span className="text-sm font-medium">
          {full ? "Reviewed" : "Ranked"} {table.rows.length} documents
          {secs && <span className="ml-1.5 text-xs font-normal text-muted-foreground">in {secs}s</span>}
        </span>
        {full && (
          <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <input type="checkbox" checked={onlyAnswered} onChange={(e) => setOnlyAnswered(e.target.checked)} />
            Only documents with an answer
          </label>
        )}
      </div>
      <div className="max-h-[480px] overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className="sticky top-0 bg-card">
            <tr>
              <th className="px-3 py-2 font-semibold">Document</th>
              {table.questions.map((q) => (
                <th key={q} className="px-3 py-2 font-semibold">{q}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.slice(0, shown).map((r) => (
              <tr key={r.document_id} className="border-t border-border align-top" data-testid="review-row">
                <td className="px-3 py-2">
                  <span className="block text-foreground">{r.title || r.document_id}</span>
                  {r.matter_code && <span className="font-mono text-[10px] text-muted-foreground">{r.matter_code}</span>}
                </td>
                {full
                  ? (r.cells ?? []).map((c, i) => (
                      <td key={i} className="px-3 py-2">
                        {c.not_found ? (
                          <span className="text-muted-foreground">{c.error ? "Not reviewed" : "Not found"}</span>
                        ) : (
                          <button
                            type="button"
                            className="text-left hover:text-wine"
                            title={c.quote}
                            onClick={() =>
                              onOpen({
                                documentId: r.document_id,
                                title: r.title ?? undefined,
                                label: c.question,
                                quotes: c.quote ? [{ page: c.page, quote: c.quote, verified: c.verified }] : [],
                              })
                            }
                            data-testid="review-cell"
                          >
                            {c.answer}
                            {!c.verified && <span className="ml-1 text-[10px] text-amber-700">(quote unchecked)</span>}
                          </button>
                        )}
                      </td>
                    ))
                  : (r.relevance ?? []).map((v, i) => (
                      <td key={i} className="px-3 py-2 font-mono text-muted-foreground">{v.toFixed(2)}</td>
                    ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {rows.length > shown && (
        <button type="button" className="w-full border-t border-border py-2 text-xs text-muted-foreground hover:text-foreground"
          onClick={() => setShown((n) => n + PAGE)}>
          Show {Math.min(PAGE, rows.length - shown)} more of {rows.length - shown}
        </button>
      )}
    </div>
  );
}
