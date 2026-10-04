import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { getMyWork } from "@/api/firm";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

/** What needs me: my matters, what is due, what I am editing, comments for me, decisions. */
export function MyWork() {
  const { identityKey } = useApp();
  const work = useQuery({ queryKey: [identityKey, "my-work"], queryFn: getMyWork, enabled: Boolean(identityKey) });
  const w = work.data;
  if (!w) return null;
  const decisions = w.decisions.access_requests.length + w.decisions.conflict_checks.length;
  const empty = !w.matters.length && !w.due.length && !w.editing.length && !w.comments.length && !decisions;
  if (empty) return null;
  return (
    <section className="space-y-4" data-testid="my-work">
      <SectionLabel>Needs your attention</SectionLabel>
      <div className="grid gap-4 md:grid-cols-2">
        {w.due.length > 0 && (
          <Card title="Due in the next two weeks" icon="event">
            {w.due.slice(0, 6).map((d) => (
              <Link key={d.deadline_id} to={`/matters/${d.matter_id}`} className="flex items-baseline justify-between gap-3 py-1 text-sm hover:text-wine">
                <span className="truncate">{d.title} <span className="text-xs text-muted-foreground">{d.matter_code}</span></span>
                <span className={cn("whitespace-nowrap font-mono-id text-xs", d.overdue ? "text-destructive" : "text-muted-foreground")}>
                  {d.overdue ? "overdue " : ""}{formatDate(d.due_date)}
                </span>
              </Link>
            ))}
          </Card>
        )}
        {w.matters.length > 0 && (
          <Card title={`My matters (${w.matters.length})`} icon="gavel">
            {w.matters.slice(0, 6).map((m) => (
              <Link key={m.matter_id} to={`/matters/${m.matter_id}`} className="flex items-baseline justify-between gap-3 py-1 text-sm hover:text-wine"
                data-testid="my-work-matter">
                <span className="truncate">{m.title}</span>
                <span className="whitespace-nowrap text-xs text-muted-foreground">{m.role_on_matter}</span>
              </Link>
            ))}
          </Card>
        )}
        {w.editing.length > 0 && (
          <Card title="Documents in progress" icon="edit_document">
            {w.editing.map((d) => (
              <Link key={`${d.document_id}-${d.state}`} to={`/documents/${d.document_id}/edit`} className="flex justify-between gap-3 py-1 text-sm hover:text-wine">
                <span className="truncate">{d.title}</span>
                <span className="text-xs text-muted-foreground">{d.state === "editing" ? "editing now" : "unsaved draft"}</span>
              </Link>
            ))}
          </Card>
        )}
        {w.comments.length > 0 && (
          <Card title="Comments for you" icon="forum">
            {w.comments.slice(0, 6).map((c) => (
              <Link key={c.comment_id} to={`/documents/${c.document_id}/edit`} className="block py-1 text-sm hover:text-wine">
                <span className="font-medium">{c.author_name}</span>
                <span className="text-muted-foreground"> {c.why === "reply" ? "replied" : "commented"} on {c.title}: </span>
                <span className="line-clamp-1">{c.body}</span>
              </Link>
            ))}
          </Card>
        )}
        {decisions > 0 && (
          <Card title="Waiting for your decision" icon="how_to_reg">
            {w.decisions.access_requests.map((r) => (
              <Link key={r.request_id} to={`/matters/${r.matter_id}`} className="block py-1 text-sm hover:text-wine">
                {r.requester_name ?? "Someone"} asks for {r.level} access to {r.matter_code}
              </Link>
            ))}
            {w.decisions.conflict_checks.map((c) => (
              <Link key={c.check_id} to="/clients" className="block py-1 text-sm hover:text-wine">
                Conflict check: {c.names.join(", ")}
              </Link>
            ))}
          </Card>
        )}
      </div>
    </section>
  );
}

function Card({ title, icon, children }: { title: string; icon: string; children: React.ReactNode }) {
  return (
    <div className="rounded-lg border border-border bg-card p-4">
      <div className="mb-2 flex items-center gap-2 text-sm font-semibold">
        <Icon name={icon} style={{ fontSize: 18 }} /> {title}
      </div>
      <div className="divide-y divide-border/60">{children}</div>
    </div>
  );
}
