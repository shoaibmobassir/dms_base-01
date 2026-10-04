import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  CommandDialog,
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
import { useTheme } from "@/lib/theme";

const QUICK_LINKS = [
  { label: "Home", to: "/", icon: "home" },
  { label: "Ask the Firm", to: "/ask", icon: "manage_search" },
  { label: "Assistant", to: "/chat", icon: "edit_note" },
  { label: "Matters", to: "/matters", icon: "gavel" },
  { label: "Clients", to: "/clients", icon: "apartment" },
  { label: "Documents", to: "/documents", icon: "description" },
  { label: "People", to: "/people", icon: "groups" },
  { label: "Calendar", to: "/calendar", icon: "event" },
  { label: "Arguments", to: "/arguments", icon: "balance" },
];

/** Render a snippet whose hit words are wrapped in << >> (the search API's markers). */
function Snippet({ text }: { text: string }) {
  const parts = text.replace(/\s+/g, " ").trim().split(/(<<.*?>>)/g);
  return (
    <span className="block truncate text-xs text-muted-foreground" data-testid="search-snippet">
      {parts.map((part, i) =>
        part.startsWith("<<") && part.endsWith(">>") ? (
          <mark key={i} className="rounded-sm bg-wine-soft px-0.5 text-ink">
            {part.slice(2, -2)}
          </mark>
        ) : (
          <span key={i}>{part}</span>
        ),
      )}
    </span>
  );
}

function PaletteNote({ children, testId }: { children: React.ReactNode; testId?: string }) {
  return (
    <div role="status" data-testid={testId} className="px-3 py-3 text-sm text-muted-foreground">
      {children}
    </div>
  );
}

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
  const { theme, setTheme } = useTheme();
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
        {/* Plain messages, not CommandEmpty: cmdk hides CommandEmpty whenever an item (the Ask row) is listed. */}
        {input.trim().length === 1 && <PaletteNote>Type at least 2 characters to search.</PaletteNote>}
        {q.length >= 2 && search.isError && !search.isFetching && (
          <PaletteNote testId="search-error">
            Search failed.{" "}
            <button type="button" className="font-medium text-wine hover:underline" onClick={() => void search.refetch()}>
              Try again
            </button>
          </PaletteNote>
        )}
        {q.length >= 2 && search.isFetching && groups.length === 0 && <PaletteNote>Searching…</PaletteNote>}
        {q.length >= 2 && !search.isError && !search.isFetching && groups.length === 0 && (
          <PaletteNote testId="search-empty">No matches in titles or document text within your access scope.</PaletteNote>
        )}

        {input.trim() && (
          <CommandGroup heading="Ask">
            <CommandItem value={`ask ${input}`} onSelect={() => go(`/ask?q=${encodeURIComponent(input.trim())}`)}>
              <Icon name="manage_search" className="mr-2 text-wine" style={{ fontSize: 18 }} />
              Ask the Firm: “{input.trim()}”
            </CommandItem>
          </CommandGroup>
        )}

        {groups.map(({ kind, rows }) => (
          <CommandGroup key={kind} heading={KIND[kind].heading}>
            {rows.slice(0, 6).map((r) => (
              <CommandItem key={`${kind}-${r.id}`} value={`${kind}-${r.id}`} onSelect={() => go(`${KIND[kind].path}/${r.id}`)}>
                <Icon name={KIND[kind].icon} className="mr-2 text-muted-foreground" style={{ fontSize: 18 }} />
                <span className="min-w-0 flex-1">
                  <span className="block truncate">{r.title}</span>
                  {r.match_kind === "content" && r.snippet && <Snippet text={r.snippet} />}
                </span>
                {r.subtitle && <span className="ml-2 truncate text-xs text-muted-foreground">{r.subtitle}</span>}
              </CommandItem>
            ))}
          </CommandGroup>
        ))}

        {!input.trim() && (
          <>
            <CommandGroup heading="Actions">
              <CommandItem value="new assistant conversation" onSelect={() => go("/chat")} data-testid="command-new-conversation">
                <Icon name="edit_note" className="mr-2 text-wine" style={{ fontSize: 18 }} />
                New Assistant conversation
              </CommandItem>
              <CommandItem value="add documents upload" onSelect={() => go("/documents?add=1")} data-testid="command-add-documents">
                <Icon name="upload_file" className="mr-2 text-wine" style={{ fontSize: 18 }} />
                Add documents
              </CommandItem>
              <CommandItem value="new matter" onSelect={() => go("/matters?new=1")}>
                <Icon name="add" className="mr-2 text-wine" style={{ fontSize: 18 }} />
                New matter
              </CommandItem>
              <CommandItem
                value="toggle theme dark light"
                onSelect={() => {
                  setTheme(theme === "dark" ? "light" : "dark");
                  setOpen(false);
                }}
              >
                <Icon name="contrast" className="mr-2 text-muted-foreground" style={{ fontSize: 18 }} />
                Switch to {theme === "dark" ? "light" : "dark"} theme
              </CommandItem>
              <CommandItem value="recent conversations history" onSelect={() => go("/chat?history=open")}>
                <Icon name="history" className="mr-2 text-muted-foreground" style={{ fontSize: 18 }} />
                Open conversation history
              </CommandItem>
            </CommandGroup>
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
