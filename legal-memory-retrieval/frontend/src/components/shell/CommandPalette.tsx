import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CommandDialog,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
  CommandSeparator,
} from "@/components/ui/command";
import { Icon } from "@/components/common/primitives";
import { useSearch } from "@/api/resources";
import type { SearchResult } from "@/api/types";
import { useDebounced } from "@/lib/use-debounced";

const QUICK_LINKS = [
  { label: "Home", to: "/", icon: "home" },
  { label: "Ask the Firm", to: "/ask", icon: "forum" },
  { label: "Assistant", to: "/chat", icon: "chat" },
  { label: "Matters", to: "/matters", icon: "gavel" },
  { label: "Clients", to: "/clients", icon: "apartment" },
  { label: "Documents", to: "/documents", icon: "description" },
  { label: "People", to: "/people", icon: "groups" },
  { label: "Calendar", to: "/calendar", icon: "event" },
  { label: "Arguments", to: "/arguments", icon: "balance" },
];

const KIND: Record<SearchResult["kind"], { heading: string; icon: string; path: string }> = {
  matter: { heading: "Matters", icon: "gavel", path: "/matters" },
  document: { heading: "Documents", icon: "description", path: "/documents" },
  client: { heading: "Clients", icon: "apartment", path: "/clients" },
  member: { heading: "People", icon: "person", path: "/people" },
};

export function CommandPalette({
  open,
  setOpen,
}: {
  open: boolean;
  setOpen: (v: boolean | ((o: boolean) => boolean)) => void;
}) {
  const navigate = useNavigate();
  const [input, setInput] = useState("");
  const q = useDebounced(input.trim(), 200);
  const search = useSearch(q);

  useEffect(() => {
    const down = (e: KeyboardEvent) => {
      if (e.key === "k" && (e.metaKey || e.ctrlKey)) {
        e.preventDefault();
        setOpen((o) => !o);
      }
    };
    document.addEventListener("keydown", down);
    return () => document.removeEventListener("keydown", down);
  }, [setOpen]);

  useEffect(() => {
    if (!open) setInput("");
  }, [open]);

  const go = (to: string) => {
    setOpen(false);
    navigate(to);
  };

  const results = q.length >= 2 ? (search.data ?? []) : [];
  const groups = (Object.keys(KIND) as SearchResult["kind"][])
    .map((kind) => ({ kind, rows: results.filter((r) => r.kind === kind) }))
    .filter((g) => g.rows.length > 0);

  return (
    // Server-side search: cmdk's own filtering is off so results aren't re-filtered locally.
    <CommandDialog open={open} onOpenChange={setOpen} shouldFilter={false}>
      <CommandInput
        placeholder="Search matters, documents, clients, people…"
        value={input}
        onValueChange={setInput}
        data-testid="command-input"
      />
      <CommandList>
        {q.length >= 2 && !search.isFetching && groups.length === 0 && (
          <CommandEmpty>No results within your access scope.</CommandEmpty>
        )}

        {input.trim() && (
          <CommandGroup heading="Ask">
            <CommandItem value={`ask ${input}`} onSelect={() => go(`/ask?q=${encodeURIComponent(input.trim())}`)}>
              <Icon name="forum" className="mr-2 text-wine" style={{ fontSize: 18 }} />
              Ask the Firm: “{input.trim()}”
            </CommandItem>
          </CommandGroup>
        )}

        {groups.map(({ kind, rows }) => (
          <CommandGroup key={kind} heading={KIND[kind].heading}>
            {rows.slice(0, 6).map((r) => (
              <CommandItem key={`${kind}-${r.id}`} value={`${kind}-${r.id}`} onSelect={() => go(`${KIND[kind].path}/${r.id}`)}>
                <Icon name={KIND[kind].icon} className="mr-2 text-muted-foreground" style={{ fontSize: 18 }} />
                <span className="flex-1 truncate">{r.title}</span>
                {r.subtitle && <span className="ml-2 truncate text-xs text-muted-foreground">{r.subtitle}</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}

        {!input.trim() && (
          <>
            <CommandSeparator />
            <CommandGroup heading="Navigate">
              {QUICK_LINKS.map((link) => (
                <CommandItem key={link.to} value={link.label} onSelect={() => go(link.to)}>
                  <Icon name={link.icon} className="mr-2 text-muted-foreground" style={{ fontSize: 18 }} />
                  {link.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </>
        )}
      </CommandList>
    </CommandDialog>
  );
}
