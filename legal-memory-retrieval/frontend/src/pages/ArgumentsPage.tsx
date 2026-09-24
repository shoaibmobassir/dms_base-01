import { useEffect, useState } from "react";
import { PAGE_SIZE, useArguments } from "@/api/resources";
import { MatterLink } from "@/components/common/EntityLink";
import { EmptyState, PageHeader, SearchField } from "@/components/common/primitives";
import { Pager, QueryState } from "@/components/common/QueryState";
import { useDebounced } from "@/lib/use-debounced";
import { cn } from "@/lib/utils";

export function ArgumentsPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const [selectedId, setSelectedId] = useState("");
  const q = useDebounced(query.trim());
  const args = useArguments({ q, page });

  useEffect(() => setPage(0), [q]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Arguments"
        title="The firm's argument bank."
        subtitle="Legal propositions the firm has run before — with the matters they were used on."
      />
      <SearchField value={query} onChange={setQuery} placeholder="Search issues and arguments…" testId="arguments-search" />
      <QueryState
        query={args}
        isEmpty={(d) => d.items.length === 0}
        empty={<EmptyState icon="balance" title="No arguments found" description="Nothing matches within your access scope." />}
      >
        {(d) => {
          const selected = d.items.find((a) => a.argument_id === selectedId) ?? d.items[0];
          return (
            <>
              <div className="grid gap-8 lg:grid-cols-[340px_minmax(0,1fr)]">
                <div className="space-y-px" data-testid="arguments-list">
                  {d.items.map((a) => (
                    <button
                      key={a.argument_id}
                      type="button"
                      onClick={() => setSelectedId(a.argument_id)}
                      className={cn(
                        "block w-full border-b border-border px-2 py-4 text-left transition-colors",
                        selected.argument_id === a.argument_id ? "bg-wine-soft/50" : "hover:bg-secondary/60",
                      )}
                    >
                      <div className={cn("text-[15px]", selected.argument_id === a.argument_id ? "text-wine" : "text-foreground")}>{a.issue}</div>
                      <div className="mt-0.5 font-mono-id text-xs text-muted-foreground">{a.matter_code}</div>
                    </button>
                  ))}
                </div>
                <div className="animate-fade">
                  <div className="eyebrow text-wine">Argument · {selected.argument_id}</div>
                  <h2 className="mt-1 font-display text-2xl text-ink">{selected.issue}</h2>
                  {selected.position && <div className="mt-2 text-xs uppercase tracking-wide text-muted-foreground">{selected.position}</div>}
                  <p className="mt-3 whitespace-pre-wrap text-[15px] leading-relaxed">{selected.argument}</p>
                  {selected.outcome && <p className="mt-3 text-sm text-muted-foreground">Outcome: {selected.outcome}</p>}
                  <div className="mt-6">
                    <MatterLink id={selected.matter_id} code={selected.matter_code} name={selected.matter_title} />
                  </div>
                </div>
              </div>
              <Pager page={page} total={d.total} pageSize={PAGE_SIZE} onPage={setPage} />
            </>
          );
        }}
      </QueryState>
    </div>
  );
}
