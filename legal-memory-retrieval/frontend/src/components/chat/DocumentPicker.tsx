import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import type { DocumentItem, Paged } from "@/api/types";
import { Check, FileText, Search } from "lucide-react";
import { Sheet, SheetContent, SheetHeader, SheetTitle } from "@/components/ui/sheet";

export function DocumentPicker({
  open,
  onOpenChange,
  selected,
  onPick,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  selected: string[];
  onPick: (doc: DocumentItem) => void;
}) {
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 250);
    return () => clearTimeout(t);
  }, [query]);
  const results = useQuery({
    queryKey: ["chat-doc-picker", debounced],
    queryFn: () =>
      apiFetch<Paged<DocumentItem>>(`/api/documents?limit=30${debounced ? `&q=${encodeURIComponent(debounced)}` : ""}`),
    enabled: open,
  });

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="flex w-[420px] flex-col gap-0 p-0 sm:max-w-[420px]" data-testid="document-picker">
        <SheetHeader className="space-y-0 border-b border-border px-4 py-3 text-left">
          <SheetTitle className="font-display text-base text-ink">Attach firm documents</SheetTitle>
        </SheetHeader>
        <div className="relative border-b border-border px-4 py-2">
          <Search className="pointer-events-none absolute left-6 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            autoFocus
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search by title, number or text…"
            aria-label="Search documents"
            data-testid="document-picker-search"
            className="w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-2 text-sm placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {results.isPending && <p className="px-2 py-1 text-xs text-muted-foreground">Searching…</p>}
          {results.data?.items.length === 0 && <p className="px-2 py-1 text-xs text-muted-foreground">No documents match.</p>}
          {results.data?.items.map((d) => {
            const isOn = selected.includes(d.document_id);
            return (
              <button
                key={d.document_id}
                type="button"
                disabled={isOn}
                onClick={() => onPick(d)}
                data-testid="document-picker-item"
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-secondary disabled:opacity-60"
              >
                <FileText className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-[13px] text-ink">{d.title}</span>
                  <span className="block truncate font-mono text-xs text-muted-foreground">
                    {d.document_id} · {d.matter_code ?? d.matter_id ?? ""}
                  </span>
                </span>
                {isOn && <Check className="mt-0.5 h-3.5 w-3.5 text-success-ink" />}
              </button>
            );
          })}
        </div>
      </SheetContent>
    </Sheet>
  );
}
