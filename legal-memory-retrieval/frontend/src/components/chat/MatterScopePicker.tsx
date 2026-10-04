import { useEffect, useRef, useState } from "react";
import { Check, ChevronDown, Crosshair, Search } from "lucide-react";
import { useMatter, useMatters } from "@/api/resources";
import { cn } from "@/lib/utils";

export type MatterChoice = { matter_id: string; matter_code: string; title: string };

/**
 * Chooses the matter a conversation searches in. "All matters" searches every
 * record the member may see; a matter limits search to that matter's documents.
 */
export function MatterScopePicker({
  matterId,
  pending,
  onChange,
  disabled,
}: {
  /** The saved conversation's matter. */
  matterId?: string | null;
  /** A choice made before the conversation exists. */
  pending?: MatterChoice | null;
  onChange: (choice: MatterChoice | null) => void;
  disabled?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  const [debounced, setDebounced] = useState("");
  const boxRef = useRef<HTMLDivElement>(null);
  const saved = useMatter(matterId ?? "");
  const matters = useMatters({ q: debounced || undefined, limit: 20 });

  useEffect(() => {
    const t = setTimeout(() => setDebounced(query.trim()), 200);
    return () => clearTimeout(t);
  }, [query]);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => !boxRef.current?.contains(e.target as Node) && setOpen(false);
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  const current: MatterChoice | null = matterId
    ? saved.data
      ? { matter_id: matterId, matter_code: saved.data.matter.matter_code, title: saved.data.matter.title }
      : { matter_id: matterId, matter_code: matterId, title: "" }
    : pending ?? null;

  const choose = (choice: MatterChoice | null) => {
    setOpen(false);
    setQuery("");
    onChange(choice);
  };

  return (
    <div ref={boxRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={disabled}
        aria-expanded={open}
        aria-haspopup="listbox"
        data-testid="chat-scope"
        title={current ? `Searching only ${current.title || current.matter_code}` : "Searching every matter you can access"}
        className={cn(
          "inline-flex h-9 max-w-[260px] items-center gap-1.5 rounded-full border px-3 text-xs font-medium transition-colors disabled:opacity-50",
          current ? "border-wine/40 bg-wine-soft text-wine" : "border-border bg-card text-foreground hover:bg-secondary",
        )}
      >
        <Crosshair className="h-3.5 w-3.5 shrink-0" />
        <span className="truncate">{current ? current.matter_code : "All matters"}</span>
        <ChevronDown className="h-3.5 w-3.5 shrink-0 opacity-70" />
      </button>

      {open && (
        <div
          className="absolute bottom-full left-0 z-50 mb-1 w-[340px] max-w-[calc(100vw-2rem)] rounded-lg border border-border bg-popover p-1.5 text-popover-foreground shadow-xl"
          data-testid="chat-scope-menu"
        >
          <p className="px-2 pb-1.5 pt-1 text-[12px] text-muted-foreground">Search in</p>
          <div className="relative mb-1">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <input
              autoFocus
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Find a matter by name, code or client"
              aria-label="Find a matter"
              data-testid="chat-scope-search"
              className="w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-2 text-[13px] placeholder:text-muted-foreground focus:outline-none"
            />
          </div>
          <ul role="listbox" className="max-h-72 overflow-y-auto">
            <li>
              <button
                type="button"
                role="option"
                aria-selected={!current}
                onClick={() => choose(null)}
                className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-secondary"
              >
                <Check className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", current ? "invisible" : "text-wine")} />
                <span>
                  <span className="block text-[13px] font-medium">All matters</span>
                  <span className="block text-[12px] text-muted-foreground">Everything you have access to</span>
                </span>
              </button>
            </li>
            {matters.isPending && <li className="px-2 py-1.5 text-[12px] text-muted-foreground">Loading matters…</li>}
            {matters.data?.items.length === 0 && <li className="px-2 py-1.5 text-[12px] text-muted-foreground">No matters match.</li>}
            {matters.data?.items.map((m) => (
              <li key={m.matter_id}>
                <button
                  type="button"
                  role="option"
                  aria-selected={current?.matter_id === m.matter_id}
                  onClick={() => choose({ matter_id: m.matter_id, matter_code: m.matter_code, title: m.title })}
                  data-testid="chat-scope-option"
                  className="flex w-full items-start gap-2 rounded-md px-2 py-1.5 text-left hover:bg-secondary"
                >
                  <Check className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", current?.matter_id === m.matter_id ? "text-wine" : "invisible")} />
                  <span className="min-w-0">
                    <span className="block truncate text-[13px] font-medium">{m.title}</span>
                    <span className="block truncate font-mono text-xs text-muted-foreground">
                      {[m.matter_code, m.client_name].filter(Boolean).join(" · ")}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
