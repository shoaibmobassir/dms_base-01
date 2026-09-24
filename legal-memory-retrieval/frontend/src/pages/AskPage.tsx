import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useAsk } from "@/api/resources";
import { AIAnswer, AIAssembling, AnswerContext } from "@/components/ai/AIAnswer";
import { AskComposer } from "@/components/ai/AskComposer";
import { ErrorState, Eyebrow, Icon, PageHeader, SectionLabel } from "@/components/common/primitives";

const EXAMPLES = [
  "What did we argue on maintainability before the Appellate Tribunal for Electricity?",
  "Which matters concern transmission charges under the CERC sharing regulations?",
  "Summarise the PCIJ's approach to reparation in our historical corpus.",
  "Which Security Council resolutions did we advise on in 2025?",
];

export function AskPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q");
  const scope = params.get("scope");
  // A scope (matter code or client name) is sent as part of the question so the
  // retrieval engine's matter resolver can use it.
  const effective = q ? (scope ? `${scope}: ${q}` : q) : null;
  const ask = useAsk(effective);
  const [history, setHistory] = useState<string[]>([]);

  useEffect(() => {
    if (q) setHistory((h) => (h.includes(q) ? h : [...h, q]));
  }, [q]);

  if (!q) {
    return (
      <div className="mx-auto flex min-h-[70vh] max-w-3xl flex-col justify-center py-8">
        <div className="mb-8 text-center">
          <Eyebrow className="mb-4">Ask the Firm</Eyebrow>
          <h1 className="font-display text-5xl text-ink">What would you like to know?</h1>
          <p className="mt-4 text-muted-foreground">
            Answers are drawn only from matters and documents you are authorised to access, and every claim links to its source.
          </p>
        </div>
        <AskComposer large examples={EXAMPLES} scopeLabel={scope ?? undefined} />
      </div>
    );
  }

  return (
    <div className="grid gap-8 lg:grid-cols-[200px_minmax(0,1fr)_260px]">
      <aside className="order-2 lg:order-1">
        <SectionLabel>This session</SectionLabel>
        <div className="space-y-1">
          {history.map((h) => (
            <button
              key={h}
              type="button"
              onClick={() => setParams({ q: h, ...(scope ? { scope } : {}) })}
              className={`block w-full rounded-md px-3 py-2 text-left text-sm transition-colors ${h === q ? "bg-wine-soft font-medium text-wine" : "text-muted-foreground hover:bg-secondary"}`}
            >
              {h}
            </button>
          ))}
        </div>
      </aside>

      <div className="order-1 min-w-0 lg:order-2">
        {scope && (
          <div className="mb-4 inline-flex items-center gap-1.5 rounded-md bg-wine-soft px-2.5 py-1 text-xs font-semibold text-wine">
            <Icon name="target" style={{ fontSize: 15 }} /> Scope: {scope}
          </div>
        )}
        <PageHeader eyebrow="Ask the Firm" title={q} className="mb-8" />
        {ask.isFetching && <AIAssembling />}
        {ask.isError && (
          <ErrorState title="The answer could not be produced" description={ask.error.message} onRetry={() => void ask.refetch()} />
        )}
        {ask.data && !ask.isFetching && <AIAnswer result={ask.data} />}
        <div className="mt-10">
          <SectionLabel>Ask a follow-up</SectionLabel>
          <AskComposer scopeLabel={scope ?? undefined} placeholder="Ask a follow-up question…" />
        </div>
      </div>

      <aside className="order-3 hidden lg:block">{ask.data && !ask.isFetching && <AnswerContext result={ask.data} />}</aside>
    </div>
  );
}
