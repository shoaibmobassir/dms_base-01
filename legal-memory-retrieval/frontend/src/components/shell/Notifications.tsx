import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMyWork } from "@/api/firm";
import { Icon } from "@/components/common/primitives";
import { DropdownMenu, DropdownMenuContent, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";

/**
 * What needs the person now: overdue court dates, comments for them and decisions waiting.
 * It reads the same data as "Needs your attention" on Home, so the two always agree.
 */
export function Notifications() {
  const { identityKey } = useApp();
  const work = useQuery({ queryKey: [identityKey, "my-work"], queryFn: getMyWork, enabled: Boolean(identityKey) });
  const w = work.data;
  const overdue = (w?.due ?? []).filter((d) => d.overdue);
  const comments = w?.comments ?? [];
  const decisions = [...(w?.decisions.access_requests ?? []), ...(w?.decisions.conflict_checks ?? [])];
  const count = overdue.length + comments.length + decisions.length;
  const row = "block rounded-md px-3 py-2 text-sm hover:bg-secondary";

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="relative rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label={count ? `Notifications, ${count} need you` : "Notifications"}
          data-testid="notifications"
        >
          <Icon name="notifications" style={{ fontSize: 20 }} />
          {count > 0 && (
            <span className="absolute right-0.5 top-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-wine px-1 text-xs font-semibold leading-none text-primary-foreground" data-testid="notifications-count">
              {count > 9 ? "9+" : count}
            </span>
          )}
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="max-h-[70vh] w-80 overflow-y-auto p-1">
        {count === 0 ? (
          <p className="px-3 py-4 text-sm text-muted-foreground" data-testid="notifications-empty">Nothing needs you right now.</p>
        ) : (
          <div data-testid="notifications-list">
            {overdue.slice(0, 5).map((d) => (
              <Link key={d.deadline_id} to={`/matters/${d.matter_id}?tab=deadlines`} className={row}>
                <span className="block truncate">{d.title}</span>
                <span className="block text-xs text-destructive">Overdue since {formatDate(d.due_date)} · {d.matter_code}</span>
              </Link>
            ))}
            {comments.slice(0, 5).map((c) => (
              <Link key={c.comment_id} to={`/documents/${c.document_id}/edit`} className={row}>
                <span className="block truncate">
                  {c.author_name} {c.why === "reply" ? "replied" : "commented"} on {c.title}
                </span>
                <span className="block truncate text-xs text-muted-foreground">{c.body}</span>
              </Link>
            ))}
            {(w?.decisions.access_requests ?? []).map((r) => (
              <Link key={r.request_id} to={`/matters/${r.matter_id}`} className={row}>
                <span className="block truncate">{r.requester_name ?? "Someone"} asks for {r.level} access</span>
                <span className="block text-xs text-muted-foreground">{r.matter_code}</span>
              </Link>
            ))}
            {(w?.decisions.conflict_checks ?? []).map((c) => (
              <Link key={c.check_id} to="/clients" className={row}>
                <span className="block truncate">Conflict check: {c.names.join(", ")}</span>
              </Link>
            ))}
          </div>
        )}
        <Link to="/" className="mt-1 block border-t border-border px-3 py-2 text-xs font-semibold text-wine hover:underline">
          Open Home
        </Link>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
