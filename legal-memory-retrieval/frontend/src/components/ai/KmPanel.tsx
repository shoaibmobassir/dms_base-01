import { Link } from "react-router-dom";
import type { KmPanel as KmPanelData } from "@/api/types";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { cn } from "@/lib/utils";

const RELATION_LABEL: Record<string, string> = {
  asked: "Asked about",
  evidence: "In the evidence",
  similar: "Similar",
  related: "Related",
};

function Column({ title, count, testId, children }: { title: string; count: number; testId: string; children: React.ReactNode }) {
  return (
    <section className="min-w-0" data-testid={testId}>
      <SectionLabel>
        {title} ({count})
      </SectionLabel>
      {count === 0 ? <p className="text-sm text-muted-foreground">None found.</p> : children}
    </section>
  );
}

/**
 * The KM desk view of an answer: which matters, which documents and which people it is about.
 * Each row carries the server's reason ("Lead on …", "3 relevant passages", "precedent of …").
 */
export function KmPanel({
  panel,
  question,
  onOpenDocument,
}: {
  panel: KmPanelData;
  question: string;
  onOpenDocument: (documentId: string, title?: string) => void;
}) {
  const top = panel.matters[0];
  const assistantHref = `/chat?${new URLSearchParams({
    ...(top ? { matter: top.matter_id } : {}),
    q: question,
  }).toString()}`;

  return (
    <div className="space-y-4" data-testid="km-panel">
      <div className="grid gap-6 rounded-lg border border-border bg-card p-4 md:grid-cols-3">
        <Column title="Matters" count={panel.matters.length} testId="km-matters">
          <ul className="space-y-3">
            {panel.matters.map((m) => (
              <li key={m.matter_id} data-testid="km-matter">
                <Link to={`/matters/${m.matter_id}`} className="group block">
                  <span className="block font-mono text-xs text-muted-foreground">{m.matter_code}</span>
                  <span className="block text-sm leading-snug group-hover:text-wine">{m.title}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[m.client_name, m.status, m.lead && `Lead: ${m.lead}`].filter(Boolean).join(" · ")}
                  </span>
                </Link>
                <span
                  className={cn(
                    "mt-1 inline-block rounded px-1.5 py-0.5 text-xs font-semibold uppercase tracking-wide",
                    m.relation === "asked" ? "bg-wine-soft text-wine" : "bg-secondary text-muted-foreground",
                  )}
                  title={m.why}
                >
                  {RELATION_LABEL[m.relation] ?? m.relation}
                </span>
                {m.why && <span className="ml-1.5 text-xs text-muted-foreground">{m.why}</span>}
              </li>
            ))}
          </ul>
        </Column>

        <Column title="Documents" count={panel.documents.length} testId="km-documents">
          <ul className="space-y-3">
            {panel.documents.map((d) => (
              <li key={d.document_id} data-testid="km-document">
                <button type="button" onClick={() => onOpenDocument(d.document_id, d.title ?? undefined)} className="group block w-full text-left">
                  <span className="flex items-start gap-1 text-sm leading-snug group-hover:text-wine">
                    {d.cited && <Icon name="format_quote" className="mt-0.5 shrink-0 text-wine" style={{ fontSize: 14 }} />}
                    <span>{d.title || d.document_id}</span>
                  </span>
                  <span className="block text-xs text-muted-foreground">
                    {[d.document_type, d.doc_date, d.matter_code, d.page_number && `p. ${d.page_number}`].filter(Boolean).join(" · ")}
                  </span>
                  <span className="block text-xs text-muted-foreground">{d.why}</span>
                </button>
              </li>
            ))}
          </ul>
        </Column>

        <Column title="People" count={panel.people.length} testId="km-people">
          <ul className="space-y-3">
            {panel.people.map((p) => (
              <li key={p.member_id} data-testid="km-person">
                <Link to={`/people/${p.member_id}`} className="group block">
                  <span className="block text-sm group-hover:text-wine">{p.name}</span>
                  <span className="block text-xs text-muted-foreground">{[p.role, p.office].filter(Boolean).join(" · ")}</span>
                  <span className="block text-xs text-muted-foreground">{p.why}</span>
                </Link>
              </li>
            ))}
          </ul>
        </Column>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <Link
          to={assistantHref}
          className="inline-flex items-center gap-1.5 rounded-md border border-border px-3 py-1.5 text-sm hover:border-wine hover:text-wine"
          data-testid="km-open-assistant"
        >
          <Icon name="auto_awesome" style={{ fontSize: 16 }} /> Continue in the Assistant
        </Link>
        <span className="text-xs text-muted-foreground">
          Review, compare or draft across these documents{top ? ` — scoped to ${top.matter_code}` : ""}.
        </span>
      </div>
    </div>
  );
}
