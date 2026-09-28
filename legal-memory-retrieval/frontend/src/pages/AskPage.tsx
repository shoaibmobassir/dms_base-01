import { useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { deleteAskHistory, listAskHistory, useAskStream } from "@/api/ask";
import type { AskScopeType } from "@/api/resources";
import type { AskHistoryItem, AskResult } from "@/api/types";
import { AIAnswer, AIAssembling, AIStreaming, AnswerContext } from "@/components/ai/AIAnswer";
import { AskComposer } from "@/components/ai/AskComposer";
import { DocumentPanelProvider, useDocumentPanel } from "@/components/ai/DocumentPanelDrawer";
import { KmPanel } from "@/components/ai/KmPanel";
import { MatterBrief } from "@/components/ai/MatterBrief";
import { ErrorState, Eyebrow, Icon, SectionLabel } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const EXAMPLES = [
  "What did we argue on maintainability before the Appellate Tribunal for Electricity?",
  "Which matters concern transmission charges under the CERC sharing regulations?",
  "Summarise the PCIJ's approach to reparation in our historical corpus.",
  "Which Security Council resolutions did we advise on in 2025?",
];

export function AskPage() {
  return (
    <DocumentPanelProvider>
      <AskView />
    </DocumentPanelProvider>
  );
}

function askedWhen(iso: string) {
  const d = new Date(iso);
  const sameDay = d.toDateString() === new Date().toDateString();
  return sameDay
    ? d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
    : d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

/** The member's saved questions (server-side, so they survive a reload). */
function RecentQuestions({
  current,
  onPick,
  limit,
}: {
  current?: { q: string; scope: string | null };
  onPick: (item: AskHistoryItem) => void;
  limit?: number;
}) {
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const key = [identityKey, "ask-history"];
  const history = useQuery({ queryKey: key, queryFn: () => listAskHistory(), enabled: !!identityKey });
  const items = (history.data?.items ?? []).slice(0, limit);
  const refresh = () => queryClient.invalidateQueries({ queryKey: key });

  if (!history.data?.items.length) return null;
  return (
    <div data-testid="ask-history">
      <div className="flex items-baseline justify-between gap-2">
        <SectionLabel>Recent questions</SectionLabel>
        <button
          type="button"
          onClick={() => void deleteAskHistory().then(refresh)}
          className="text-[11px] text-muted-foreground hover:text-destructive"
          data-testid="ask-history-clear"
        >
          Clear
        </button>
      </div>
      <ul className="space-y-0.5">
        {items.map((h) => {
          const active = current && h.query === current.q && (h.scope ?? null) === (current.scope ?? null);
          return (
            <li
              key={h.id}
              className={cn("group flex items-start gap-1 rounded-md", active ? "bg-wine-soft" : "hover:bg-secondary")}
              data-testid="ask-history-item"
            >
              <button
                type="button"
                onClick={() => onPick(h)}
                aria-current={active ? "page" : undefined}
                className="min-w-0 flex-1 px-3 py-2 text-left"
              >
                <span className={cn("line-clamp-2 text-sm", active ? "font-medium text-wine" : "text-foreground/85")}>{h.query}</span>
                <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">
                  {[askedWhen(h.asked_at), h.scope].filter(Boolean).join(" · ")}
                </span>
              </button>
              <button
                type="button"
                aria-label={`Remove “${h.query}” from recent questions`}
                title="Remove"
                onClick={() => void deleteAskHistory(h.id).then(refresh)}
                className="mr-1 mt-1.5 rounded p-1 text-muted-foreground/70 hover:bg-background hover:text-foreground"
              >
                <Icon name="close" style={{ fontSize: 14 }} />
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

function AskView() {
  const [params, setParams] = useSearchParams();
  const q = params.get("q");
  const scope = params.get("scope");
  const rawType = params.get("scopeType");
  const scopeType: AskScopeType = rawType === "matter" || rawType === "client" ? rawType : "auto";
  const [runKey, setRunKey] = useState(0);
  const ask = useAskStream(q, scope ? { type: scopeType, value: scope } : null, runKey);
  const panel = useDocumentPanel();
  const { identityKey } = useApp();
  const queryClient = useQueryClient();

  // Until the final answer arrives, the page shows what was gathered.
  const context: AskResult | null =
    ask.result ??
    (ask.evidence
      ? {
          sources: ask.evidence.sources,
          resolved_scope: ask.evidence.resolved_scope,
          people: ask.evidence.people,
          matter_cards: ask.evidence.matter_cards,
          panel: ask.evidence.panel,
        }
      : null);

  // The server saves each question before it gathers evidence; refresh the list once evidence arrives.
  const gathered = !!ask.evidence || ask.phase === "done";
  useEffect(() => {
    if (q && gathered) void queryClient.invalidateQueries({ queryKey: [identityKey, "ask-history"] });
  }, [q, gathered, identityKey, queryClient]);

  // A new question starts with the document panel closed.
  const closePanel = panel?.close;
  useEffect(() => closePanel?.(), [q, closePanel]);

  const pick = (h: AskHistoryItem) =>
    setParams({ q: h.query, ...(h.scope ? { scope: h.scope, scopeType: h.scope_type ?? "auto" } : {}) });

  if (!q) {
    return (
      <div className="mx-auto flex min-h-[70vh] w-full max-w-3xl flex-col justify-center px-6 py-8">
        <div className="mb-8 text-center">
          <Eyebrow className="mb-4">Ask the Firm</Eyebrow>
          <h1 className="font-display text-5xl text-ink">What would you like to know?</h1>
          <p className="mt-4 text-muted-foreground">
            Answers are drawn only from matters and documents you are authorised to access, and every claim links to its source.
          </p>
        </div>
        <AskComposer large examples={EXAMPLES} scopeLabel={scope ?? undefined} scopeType={scopeType} />
        <div className="mt-10">
          <RecentQuestions onPick={pick} limit={5} />
        </div>
      </div>
    );
  }

  // With a document open the page narrows to the answer, as in the Assistant.
  const split = !!panel?.isOpen;
  const cards = context?.matter_cards ?? [];
  const km = context?.panel;
  const abstainedOnRecords = !!ask.result?.abstained && ask.result.status !== "not_found";

  return (
    <div className={cn("mx-auto w-full px-6 py-8 lg:px-10 lg:py-10", split ? "max-w-3xl" : "max-w-[1180px]")}>
      <div className={cn("grid gap-8", !split && "lg:grid-cols-[200px_minmax(0,1fr)_260px]")}>
        {!split && (
          <aside className="order-2 lg:order-1">
            <RecentQuestions current={{ q, scope }} onPick={pick} />
          </aside>
        )}

        <div className="order-1 min-w-0 lg:order-2">
          {scope && (
            <div className="mb-4 inline-flex items-center gap-1.5 rounded-md bg-wine-soft px-2.5 py-1 text-xs font-semibold text-wine">
              <Icon name="target" style={{ fontSize: 15 }} /> Scope: {scope}
            </div>
          )}
          <header className="mb-8 animate-rise">
            <Eyebrow className="mb-3">Ask the Firm</Eyebrow>
            <h1 className="max-w-2xl text-balance font-display text-2xl leading-tight text-ink sm:text-[32px]" data-testid="ask-question">
              {q}
            </h1>
          </header>
          {ask.phase === "gathering" && <AIAssembling />}
          {(ask.phase === "writing" || ask.phase === "verifying") && (
            <AIStreaming keyFinding={ask.keyFinding} text={ask.text} verifying={ask.phase === "verifying"} />
          )}
          {ask.phase === "error" && (
            <ErrorState
              title="The answer could not be produced"
              description={ask.error ?? "Unknown error"}
              onRetry={() => setRunKey((k) => k + 1)}
            />
          )}
          {ask.phase === "done" && ask.result && <AIAnswer result={ask.result} />}
          {km && (km.matters.length > 0 || km.people.length > 0) && ask.phase !== "error" && (
            <div className="mt-10">
              {abstainedOnRecords && <p className="mb-2 text-xs text-muted-foreground">Closest records found:</p>}
              <KmPanel panel={km} question={q} onOpenDocument={(id, title) => panel?.openDocument(id, { title })} />
            </div>
          )}
          {cards.length === 1 && !abstainedOnRecords && (
            <div className="mt-10">
              <MatterBrief cards={cards} />
            </div>
          )}
          <div className="mt-10">
            <SectionLabel>Ask a follow-up</SectionLabel>
            <AskComposer scopeLabel={scope ?? undefined} scopeType={scopeType} placeholder="Ask a follow-up question…" />
          </div>
        </div>

        {!split && <aside className="order-3 hidden lg:block">{context && <AnswerContext result={context} withPanel={!!km} />}</aside>}
      </div>
    </div>
  );
}
