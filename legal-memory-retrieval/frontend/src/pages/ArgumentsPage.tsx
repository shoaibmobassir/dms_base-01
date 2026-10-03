import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { PAGE_SIZE, useArguments } from "@/api/resources";
import type { ArgumentItem, ArgumentKind } from "@/api/types";
import { MatterLink } from "@/components/common/EntityLink";
import { EmptyState, Icon, PageHeader, SearchField, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { Sheet, SheetContent, SheetTitle } from "@/components/ui/sheet";
import { useMediaQuery } from "@/lib/use-media-query";
import { cn } from "@/lib/utils";

// The bank holds three kinds of record; the filter keeps them apart.
const KINDS: { value: ArgumentKind | ""; label: string; hint: string }[] = [
  { value: "", label: "All", hint: "Every record" },
  { value: "disputes", label: "Disputes and petitions", hint: "Arguments run before courts, tribunals and commissions" },
  { value: "pcij", label: "PCIJ cases", hint: "Permanent Court of International Justice docket" },
  { value: "unsc", label: "Security Council", hint: "Resolutions the firm advised on" },
];

const KIND_LABEL: Record<ArgumentKind, string> = {
  disputes: "Dispute",
  pcij: "PCIJ case",
  unsc: "Security Council",
};

function positionLabel(a: ArgumentItem) {
  // "Client" in the data means "argued for our client"; anything longer is the proposition itself.
  if (!a.position || a.position === "Client") return null;
  return a.position;
}

function ArgumentDetail({ a }: { a: ArgumentItem }) {
  const proposition = positionLabel(a);
  const docs = a.supporting_documents ?? [];
  return (
    <article className="animate-fade space-y-5" data-testid="argument-detail">
      <div>
        <div className="flex flex-wrap items-center gap-2">
          <span className="eyebrow text-wine">{a.kind ? KIND_LABEL[a.kind] : "Argument"}</span>
          <span className="font-mono-id text-xs text-muted-foreground">{a.argument_id}</span>
        </div>
        <h2 className="mt-1 text-balance font-display text-2xl leading-snug text-ink">{a.issue}</h2>
        {proposition && <p className="mt-2 text-[15px] font-medium text-foreground">{proposition}</p>}
        <p className="mt-2 whitespace-pre-wrap text-[15px] leading-relaxed text-foreground/90">{a.argument}</p>
      </div>

      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-3">
        <div>
          <dt className="meta-label text-xs">Forum</dt>
          <dd className="mt-0.5 text-sm">{a.court || "—"}</dd>
        </div>
        <div>
          <dt className="meta-label text-xs">Outcome</dt>
          <dd className="mt-0.5 text-sm">{a.outcome || (a.matter_status ? <StatusLabel status={a.matter_status} /> : "—")}</dd>
        </div>
        <div>
          <dt className="meta-label text-xs">Opened</dt>
          <dd className="mt-0.5 text-sm tabular-nums">{formatDate(a.opened_date)}</dd>
        </div>
        <div>
          <dt className="meta-label text-xs">Led by</dt>
          <dd className="mt-0.5 text-sm">
            {a.lead_member_id ? (
              <Link to={`/people/${a.lead_member_id}`} className="hover:text-wine hover:underline">
                {a.lead_name}
              </Link>
            ) : (
              "—"
            )}
          </dd>
        </div>
        <div>
          <dt className="meta-label text-xs">Practice</dt>
          <dd className="mt-0.5 text-sm">{a.practice_area || "—"}</dd>
        </div>
        <div>
          <dt className="meta-label text-xs">Matter type</dt>
          <dd className="mt-0.5 text-sm">{a.matter_type || "—"}</dd>
        </div>
      </dl>

      <div>
        <SectionLabel>Matter</SectionLabel>
        <MatterLink id={a.matter_id} code={a.matter_code} name={a.matter_title} />
      </div>

      <div data-testid="argument-documents">
        <SectionLabel>Supporting documents ({docs.length})</SectionLabel>
        {docs.length === 0 ? (
          <p className="text-sm text-muted-foreground">No documents are linked to this record.</p>
        ) : (
          <ul className="divide-y divide-border rounded-md border border-border">
            {docs.map((d) => (
              <li key={d.document_id}>
                <Link to={`/documents/${d.document_id}`} className="flex items-center gap-2.5 px-3 py-2 text-sm hover:bg-secondary/60">
                  <Icon name="description" className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
                  <span className="min-w-0 flex-1 truncate">{d.title}</span>
                  {d.document_type && <span className="shrink-0 text-xs text-muted-foreground">{d.document_type}</span>}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </div>

      <Link
        to={`/ask?q=${encodeURIComponent(`What did we argue on ${a.issue}?`)}&scope=${encodeURIComponent(a.matter_code)}&scopeType=matter`}
        className="inline-flex items-center gap-1.5 rounded-md border border-border bg-card px-3 py-1.5 text-sm font-medium hover:bg-secondary"
      >
        <Icon name="manage_search" style={{ fontSize: 16 }} /> Ask the Firm about this argument
      </Link>
    </article>
  );
}

export function ArgumentsPage() {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState<ArgumentKind | "">("");
  const [page, setPage] = useState(0);
  // The chosen record is in the URL (?id=), so a link opens straight to it.
  const [params, setParams] = useSearchParams();
  const selectedId = params.get("id") ?? "";
  const [sheetOpen, setSheetOpen] = useState(false);
  const isLg = useMediaQuery("(min-width: 1024px)");
  const setSelectedId = (id: string) => {
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      next.set("id", id);
      return next;
    }, { replace: true });
    if (!isLg) setSheetOpen(true);
  };
  const q = useDebounced(query.trim());
  const args = useArguments({ q, kind: kind || undefined, page });
  const counts = args.data?.kinds ?? {};
  const all = Object.values(counts).reduce((n, c) => n + (c ?? 0), 0);

  useEffect(() => setPage(0), [q, kind]);

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Arguments"
        count={args.data ? `${args.data.total} records` : undefined}
        subtitle="Legal propositions the firm has run, with the forum, outcome and documents behind them."
      />
      <div className="space-y-3">
        <SearchField value={query} onChange={setQuery} placeholder="Search issues, arguments or forums…" testId="arguments-search" />
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Kind">
          {KINDS.map((k) => (
            <button
              key={k.value || "all"}
              type="button"
              title={k.hint}
              onClick={() => setKind(k.value)}
              aria-pressed={kind === k.value}
              data-testid={`arguments-kind-${k.value || "all"}`}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                kind === k.value ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary",
              )}
            >
              {k.label}
              <span className="ml-1 tabular-nums opacity-70">{k.value ? counts[k.value] ?? 0 : all}</span>
            </button>
          ))}
        </div>
      </div>
      <QueryState
        query={args}
        isEmpty={(d) => d.items.length === 0}
        empty={<EmptyState icon="balance" title="No arguments found" description="Nothing matches within your access scope." />}
      >
        {(d) => {
          const selected = d.items.find((a) => a.argument_id === selectedId) ?? d.items[0];
          return (
            <>
              <div className="grid gap-8 lg:grid-cols-[360px_minmax(0,1fr)]">
                <div className="space-y-px" data-testid="arguments-list">
                  {d.items.map((a) => {
                    const on = selected.argument_id === a.argument_id;
                    return (
                      <button
                        key={a.argument_id}
                        type="button"
                        onClick={() => setSelectedId(a.argument_id)}
                        aria-current={on ? "true" : undefined}
                        className={cn(
                          "block w-full border-b border-border px-3 py-3 text-left transition-colors",
                          on ? "bg-wine-soft/50 shadow-[inset_3px_0_0_var(--wine)]" : "hover:bg-secondary/60",
                        )}
                      >
                        <div className={cn("line-clamp-2 text-[14px] first-letter:uppercase", on ? "text-wine" : "text-foreground")}>{a.issue}</div>
                        <div className="mt-1 truncate text-xs text-muted-foreground">
                          {[a.kind ? KIND_LABEL[a.kind] : null, a.court, a.matter_code].filter(Boolean).join(" · ")}
                        </div>
                      </button>
                    );
                  })}
                </div>
                {isLg && <ArgumentDetail a={selected} />}
              </div>
              <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
              <Sheet open={!isLg && sheetOpen} onOpenChange={setSheetOpen}>
                <SheetContent side="right" className="w-full max-w-full overflow-y-auto p-6 sm:max-w-lg" aria-describedby={undefined}>
                  <SheetTitle className="sr-only">Argument</SheetTitle>
                  <div className="pt-6">
                    <ArgumentDetail a={selected} />
                  </div>
                </SheetContent>
              </Sheet>
            </>
          );
        }}
      </QueryState>
    </div>
  );
}
