import { useState } from "react";
import { MoreHorizontal, PanelLeftClose, Pencil, Pin, PinOff, Plus, Search, Trash2 } from "lucide-react";
import type { ChatSession } from "@/api/types";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

// ── grouping and labels ───────────────────────────────────────────────────────

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function daysAgo(iso: string) {
  return Math.round((startOfDay(new Date()) - startOfDay(new Date(iso))) / 86_400_000);
}

function dayGroup(iso: string) {
  const diff = daysAgo(iso);
  if (diff === 0) return "Today";
  if (diff === 1) return "Yesterday";
  if (diff < 7) return "This week";
  return new Date(iso).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

/** Short time for the row: 14:02 today, "Tue" this week, "12 Aug" otherwise. */
function when(iso: string) {
  const d = new Date(iso);
  const diff = daysAgo(iso);
  if (diff === 0) return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  if (diff < 7) return d.toLocaleDateString(undefined, { weekday: "short" });
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export function groupSessions(sessions: ChatSession[]) {
  const pinned = sessions.filter((s) => s.pinned);
  const groups: { label: string; items: ChatSession[] }[] = pinned.length ? [{ label: "Pinned", items: pinned }] : [];
  for (const s of sessions) {
    if (s.pinned) continue;
    const label = dayGroup(s.updated_at);
    const g = groups.find((x) => x.label === label);
    if (g) g.items.push(s);
    else groups.push({ label, items: [s] });
  }
  return groups;
}

export function sessionTitle(s: Pick<ChatSession, "title" | "created_at">) {
  return s.title?.trim() || `Untitled · ${when(s.created_at)}`;
}

// ── pane ──────────────────────────────────────────────────────────────────────

export function HistoryPane({
  sessions,
  activeId,
  loading,
  onNew,
  onOpen,
  onRename,
  onDelete,
  onPin,
  onCollapse,
}: {
  sessions: ChatSession[];
  activeId?: string;
  loading: boolean;
  onNew: () => void;
  onOpen: (id: string) => void;
  onRename: (id: string, title: string) => Promise<void>;
  onDelete: (id: string) => Promise<void>;
  onPin: (id: string, pinned: boolean) => Promise<void>;
  /** Desktop only: the sheet used on small screens brings its own close button. */
  onCollapse?: () => void;
}) {
  const [editing, setEditing] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [confirming, setConfirming] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [onlyPinned, setOnlyPinned] = useState(false);
  const pinnedCount = sessions.filter((s) => s.pinned).length;
  const showPinned = onlyPinned && pinnedCount > 0;

  const q = query.trim().toLowerCase();
  const filtered = sessions.filter(
    (s) => (!showPinned || s.pinned) && (!q || `${s.title ?? ""} ${s.matter_code ?? ""} ${s.matter_id ?? ""} ${s.first_question ?? ""}`.toLowerCase().includes(q)),
  );
  const groups = groupSessions(filtered);

  return (
    <div className="flex h-full min-h-0 flex-col bg-paper" data-testid="chat-history">
      <div className={cn("flex items-center justify-between gap-2 px-3 pb-2 pt-3", !onCollapse && "pr-12")}>
        <div className="min-w-0">
          <h2 className="font-display text-base text-ink">History</h2>
          {!loading && (
            <p className="text-[11px] text-muted-foreground" data-testid="chat-history-count">
              {sessions.length} {sessions.length === 1 ? "conversation" : "conversations"}
            </p>
          )}
        </div>
        {onCollapse && (
          <button
            type="button"
            onClick={onCollapse}
            title="Hide history (Alt+H)"
            aria-label="Hide history"
            className="rounded-md p-1.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
          >
            <PanelLeftClose className="h-4 w-4" />
          </button>
        )}
      </div>

      <div className="space-y-2 px-3 pb-2">
        <button
          type="button"
          onClick={onNew}
          data-testid="chat-new-drawer"
          className="flex w-full items-center justify-center gap-1.5 rounded-md bg-primary px-3 py-1.5 text-[13px] font-semibold text-primary-foreground hover:bg-primary/90"
        >
          <Plus className="h-4 w-4" />
          New conversation
        </button>
        <div className="relative">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
          <input
            type="search"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="Search titles, matters, questions"
            aria-label="Search conversations"
            data-testid="chat-history-search"
            className="w-full rounded-md border border-border bg-card py-1.5 pl-8 pr-2 text-[13px] placeholder:text-muted-foreground focus:border-wine/50 focus:outline-hidden"
          />
        </div>
        {pinnedCount > 0 && (
          <div className="flex gap-1" role="group" aria-label="Show">
            {([
              [false, "All"],
              [true, `Pinned · ${pinnedCount}`],
            ] as const).map(([value, label]) => (
              <button
                key={label}
                type="button"
                aria-pressed={showPinned === value}
                onClick={() => setOnlyPinned(value)}
                data-testid={value ? "chat-history-filter-pinned" : "chat-history-filter-all"}
                className={cn(
                  "rounded-full border px-2.5 py-0.5 text-[12px]",
                  showPinned === value ? "border-wine/40 bg-wine-soft font-semibold text-wine" : "border-border text-muted-foreground hover:text-foreground",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        )}
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto px-2 pb-3" data-testid="chat-sessions">
        {loading && <p className="px-2 py-1 text-xs text-muted-foreground">Loading…</p>}
        {!loading && groups.length === 0 && (
          <p className="px-2 py-1 text-xs text-muted-foreground">{q ? "No conversations match." : "No conversations yet."}</p>
        )}
        {groups.map((g) => (
          <div key={g.label} className="mt-2">
            <div className="px-2 pb-1 font-mono text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">{g.label}</div>
            <div className="space-y-px">
              {g.items.map((s) => {
                const isActive = s.id === activeId;
                return (
                  <div
                    key={s.id}
                    data-testid="chat-session-row"
                    className={cn(
                      "group relative flex items-start gap-1 rounded-md py-1.5 pl-2.5 pr-1 transition-colors",
                      isActive ? "bg-wine-soft" : "hover:bg-secondary",
                    )}
                  >
                    {isActive && <span className="absolute inset-y-1 left-0 w-[3px] rounded-full bg-wine" />}
                    {editing === s.id ? (
                      <input
                        autoFocus
                        value={draft}
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => {
                          if (e.key === "Enter" && draft.trim()) void onRename(s.id, draft.trim()).then(() => setEditing(null));
                          if (e.key === "Escape") setEditing(null);
                        }}
                        onBlur={() => setEditing(null)}
                        aria-label="Conversation title"
                        className="min-w-0 flex-1 rounded border border-border bg-card px-1.5 py-1 text-[13px] text-foreground"
                      />
                    ) : confirming === s.id ? (
                      <div className="flex flex-1 items-center justify-between gap-2 py-1 text-[12px]">
                        <span className="text-foreground">Delete this conversation?</span>
                        <span className="flex shrink-0 gap-2">
                          <button
                            type="button"
                            className="font-semibold text-destructive hover:underline"
                            onClick={() => void onDelete(s.id).then(() => setConfirming(null))}
                          >
                            Delete
                          </button>
                          <button type="button" onClick={() => setConfirming(null)} className="text-muted-foreground hover:underline">
                            Cancel
                          </button>
                        </span>
                      </div>
                    ) : (
                      <>
                        <button
                          type="button"
                          onClick={() => onOpen(s.id)}
                          aria-current={isActive ? "page" : undefined}
                          className="min-w-0 flex-1 text-left"
                        >
                          <span
                            className={cn(
                              "line-clamp-2 text-[13px] font-medium leading-snug",
                              isActive ? "text-wine" : "text-foreground",
                            )}
                          >
                            {s.pinned && <Pin aria-label="Pinned" className="mr-1 inline h-3 w-3 -translate-y-px text-wine" />}
                            {sessionTitle(s)}
                          </span>
                          <span className="mt-0.5 block truncate font-mono text-[11px] text-muted-foreground">
                            {[when(s.updated_at), s.matter_code ?? s.matter_id].filter(Boolean).join(" · ")}
                          </span>
                        </button>
                        <DropdownMenu>
                          <DropdownMenuTrigger asChild>
                            <button
                              type="button"
                              aria-label={`Actions for ${sessionTitle(s)}`}
                              data-testid="chat-session-menu"
                              className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md text-muted-foreground hover:bg-background hover:text-foreground data-[state=open]:bg-background"
                            >
                              <MoreHorizontal className="h-4 w-4" />
                            </button>
                          </DropdownMenuTrigger>
                          <DropdownMenuContent align="end" className="w-40" onCloseAutoFocus={(e) => e.preventDefault()}>
                            <DropdownMenuItem
                              onSelect={() => {
                                setDraft(s.title ?? "");
                                setEditing(s.id);
                              }}
                            >
                              <Pencil className="mr-2 h-3.5 w-3.5" /> Rename
                            </DropdownMenuItem>
                            <DropdownMenuItem onSelect={() => void onPin(s.id, !s.pinned)}>
                              {s.pinned ? <PinOff className="mr-2 h-3.5 w-3.5" /> : <Pin className="mr-2 h-3.5 w-3.5" />}
                              {s.pinned ? "Unpin" : "Pin to top"}
                            </DropdownMenuItem>
                            <DropdownMenuSeparator />
                            <DropdownMenuItem onSelect={() => setConfirming(s.id)} className="text-destructive focus:text-destructive">
                              <Trash2 className="mr-2 h-3.5 w-3.5" /> Delete
                            </DropdownMenuItem>
                          </DropdownMenuContent>
                        </DropdownMenu>
                      </>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
