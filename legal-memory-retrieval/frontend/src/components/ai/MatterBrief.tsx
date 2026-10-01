import { useState, type ReactNode } from "react";
import { Link } from "react-router-dom";
import type { MatterCard } from "@/api/types";
import { useDocumentPanel } from "@/components/ai/DocumentPanelDrawer";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { useStartConversation } from "@/components/chat/useStartConversation";
import { formatDate as format } from "@/lib/format";
import { cn } from "@/lib/utils";

// Everything the firm holds on the matters an answer is about: who, what, where,
// which documents and what is due. Data comes with the answer (matter_cards).

function formatDate(iso?: string | null) {
  return iso ? format(iso) : null;
}

function daysUntil(iso: string) {
  const due = new Date(iso);
  const today = new Date();
  due.setHours(0, 0, 0, 0);
  today.setHours(0, 0, 0, 0);
  return Math.round((due.getTime() - today.getTime()) / 86_400_000);
}

function StatusPill({ status }: { status?: string | null }) {
  if (!status) return null;
  const open = status.toLowerCase() === "open" || status.toLowerCase() === "active";
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[11px] font-semibold uppercase tracking-wider",
        open ? "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400" : "bg-secondary text-muted-foreground",
      )}
    >
      <span className={cn("h-1.5 w-1.5 rounded-full", open ? "bg-emerald-500" : "bg-muted-foreground")} />
      {status}
    </span>
  );
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  if (children == null || children === "") return null;
  return (
    <div className="min-w-0">
      <dt className="meta-label text-[11px]">{label}</dt>
      <dd className="mt-0.5 text-sm text-foreground">{children}</dd>
    </div>
  );
}

function Expandable<T>({ items, first, render, noun }: { items: T[]; first: number; render: (item: T, i: number) => ReactNode; noun: string }) {
  const [all, setAll] = useState(false);
  const shown = all ? items : items.slice(0, first);
  return (
    <>
      {shown.map(render)}
      {items.length > first && (
        <li className="list-none px-3 py-1.5">
          <button type="button" onClick={() => setAll((v) => !v)} className="text-xs font-medium text-wine hover:underline">
            {all ? "Show fewer" : `Show all ${items.length} ${noun}`}
          </button>
        </li>
      )}
    </>
  );
}

function MatterActions({ card }: { card: MatterCard }) {
  const { start } = useStartConversation();
  const openInAssistant = () => start(card.matter_id);
  const btn = "inline-flex items-center gap-1 rounded-md border border-border bg-card px-2.5 py-1 text-xs font-medium text-foreground hover:bg-secondary";
  return (
    <div className="flex flex-wrap gap-1.5">
      <Link to={`/matters/${card.matter_id}`} className={btn} data-testid="brief-open-matter">
        <Icon name="open_in_new" style={{ fontSize: 14 }} /> Open matter
      </Link>
      <Link to={`/ask?scope=${encodeURIComponent(card.matter_code)}&scopeType=matter`} className={btn}>
        <Icon name="manage_search" style={{ fontSize: 14 }} /> Ask about this matter
      </Link>
      <button type="button" onClick={openInAssistant} className={btn} data-testid="brief-open-assistant">
        <Icon name="edit_note" style={{ fontSize: 14 }} /> Work on it in Assistant
      </button>
    </div>
  );
}

/** The full record for one matter. */
function MatterDetail({ card }: { card: MatterCard }) {
  const panel = useDocumentPanel();
  const team = card.team ?? [];
  const docs = card.documents ?? [];
  const deadlines = card.deadlines ?? [];
  const facts = card.facts ?? [];
  const issues = card.legal_issues ?? [];
  const docTotal = card.document_count ?? docs.length;

  return (
    <div className="space-y-5">
      <dl className="grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-3">
        <Fact label="Client">{card.client_name}</Fact>
        <Fact label="Opposing party">{card.opposing_party}</Fact>
        <Fact label="Forum">{card.court}</Fact>
        <Fact label="Practice area">{card.practice_area}</Fact>
        <Fact label="Matter type">{card.matter_type}</Fact>
        <Fact label="Jurisdiction">{card.jurisdiction}</Fact>
        <Fact label="Office">{card.office}</Fact>
        <Fact label="Opened">{formatDate(card.opened_date)}</Fact>
        {card.closed_date && <Fact label="Closed">{formatDate(card.closed_date)}</Fact>}
        <Fact label="Claim">{card.claim_amount}</Fact>
        <Fact label="Outcome">{card.outcome}</Fact>
      </dl>

      {team.length > 0 && (
        <section data-testid="brief-team">
          <SectionLabel>Working on it ({team.length})</SectionLabel>
          <ul className="grid gap-2 sm:grid-cols-2">
            {team.map((p) => (
              <li key={p.member_id}>
                <Link to={`/people/${p.member_id}`} className="group flex items-center gap-2.5 rounded-md border border-border px-2.5 py-2 hover:bg-secondary/60">
                  <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-wine-soft text-xs font-semibold text-wine">
                    {p.name.split(/\s+/).map((w) => w[0]).slice(0, 2).join("")}
                  </span>
                  <span className="min-w-0">
                    <span className="block truncate text-sm font-medium text-foreground group-hover:text-wine">
                      {p.name}
                      {p.role_on_matter?.toLowerCase() === "lead" && (
                        <span className="ml-1.5 rounded bg-wine px-1 py-px align-middle text-[10px] font-semibold uppercase text-primary-foreground">Lead</span>
                      )}
                    </span>
                    <span className="block truncate text-xs text-muted-foreground">{[p.role, p.office].filter(Boolean).join(" · ")}</span>
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </section>
      )}

      {deadlines.length > 0 && (
        <section data-testid="brief-deadlines">
          <SectionLabel>Open deadlines ({deadlines.length})</SectionLabel>
          <ul className="divide-y divide-border rounded-md border border-border">
            {deadlines.map((d, i) => {
              const days = daysUntil(d.due_date);
              return (
                <li key={i} className="flex items-baseline gap-3 px-3 py-2 text-sm">
                  <span className="w-24 shrink-0 font-mono text-xs tabular-nums text-foreground">{formatDate(d.due_date)}</span>
                  <span className="min-w-0 flex-1">
                    {d.title}
                    {d.court && <span className="text-muted-foreground"> · {d.court}</span>}
                  </span>
                  <span className={cn("shrink-0 text-xs font-medium", days < 0 ? "text-destructive" : days <= 14 ? "text-amber-700 dark:text-amber-400" : "text-muted-foreground")}>
                    {days < 0 ? `${-days} days overdue` : days === 0 ? "Today" : `in ${days} days`}
                  </span>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      {docs.length > 0 && (
        <section data-testid="brief-documents">
          <SectionLabel>Documents ({docTotal})</SectionLabel>
          <ul className="divide-y divide-border rounded-md border border-border">
            <Expandable
              items={docs}
              first={5}
              noun="listed documents"
              render={(d) => (
                <li key={d.document_id}>
                  <button
                    type="button"
                    onClick={() => panel?.openDocument(d.document_id, { title: d.title })}
                    className="flex w-full items-baseline gap-3 px-3 py-2 text-left hover:bg-secondary/60"
                  >
                    <Icon name="description" className="shrink-0 self-center text-amber-600" style={{ fontSize: 16 }} />
                    <span className="min-w-0 flex-1 truncate text-sm text-foreground">{d.title}</span>
                    <span className="shrink-0 text-xs text-muted-foreground">{[d.document_type, formatDate(d.doc_date)].filter(Boolean).join(" · ")}</span>
                  </button>
                </li>
              )}
            />
          </ul>
          {docTotal > docs.length && (
            <Link to={`/matters/${card.matter_id}`} className="mt-1.5 inline-block text-xs font-medium text-wine hover:underline">
              See all {docTotal} documents on the matter page
            </Link>
          )}
        </section>
      )}

      {(facts.length > 0 || issues.length > 0) && (
        <div className="grid gap-5 sm:grid-cols-2">
          {facts.length > 0 && (
            <section>
              <SectionLabel>Key facts</SectionLabel>
              <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90">
                <Expandable items={facts} first={3} noun="facts" render={(f, i) => <li key={i}>{f}</li>} />
              </ul>
            </section>
          )}
          {issues.length > 0 && (
            <section>
              <SectionLabel>Legal issues</SectionLabel>
              <ul className="list-disc space-y-1 pl-5 text-sm text-foreground/90">
                <Expandable items={issues} first={3} noun="issues" render={(f, i) => <li key={i}>{f}</li>} />
              </ul>
            </section>
          )}
        </div>
      )}

      <MatterActions card={card} />
    </div>
  );
}

function MatterHeading({ card, as = "h2" }: { card: MatterCard; as?: "h2" | "h3" }) {
  const H = as;
  return (
    <div className="min-w-0">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-mono-id text-[11px] text-muted-foreground">{card.matter_code}</span>
        <StatusPill status={card.status} />
      </div>
      <H className={cn("mt-1 font-display leading-snug text-ink", as === "h2" ? "text-xl" : "text-base")}>{card.title}</H>
      {(card.client_name || card.opposing_party) && (
        <p className="text-sm text-muted-foreground">
          {card.client_name}
          {card.opposing_party && <> v. {card.opposing_party}</>}
        </p>
      )}
    </div>
  );
}

/** One matter in full; several as a list that opens one at a time. */
export function MatterBrief({ cards }: { cards: MatterCard[] }) {
  const [openId, setOpenId] = useState<string | null>(null);
  if (!cards.length) return null;

  if (cards.length === 1) {
    const card = cards[0];
    return (
      <section className="rounded-lg border border-border bg-card p-5" data-testid="matter-brief">
        <div className="meta-label mb-3 text-[11px] text-wine">The matter</div>
        <div className="mb-5">
          <MatterHeading card={card} />
        </div>
        <MatterDetail card={card} />
      </section>
    );
  }

  const shown = cards.slice(0, 8);
  return (
    <section data-testid="matter-brief">
      <SectionLabel>Matters in this answer ({cards.length})</SectionLabel>
      <div className="divide-y divide-border rounded-lg border border-border bg-card">
        {shown.map((card) => {
          const open = openId === card.matter_id;
          const lead = card.team?.find((t) => t.role_on_matter?.toLowerCase() === "lead");
          return (
            <div key={card.matter_id} data-testid="matter-brief-item">
              <button
                type="button"
                onClick={() => setOpenId(open ? null : card.matter_id)}
                aria-expanded={open}
                className="flex w-full items-start gap-3 px-4 py-3 text-left hover:bg-secondary/40"
              >
                <MatterHeading card={card} as="h3" />
                <span className="ml-auto hidden shrink-0 text-right text-xs text-muted-foreground sm:block">
                  {lead && <span className="block">Lead: {lead.name}</span>}
                  <span className="block">{card.document_count ?? 0} documents</span>
                </span>
                <Icon name={open ? "expand_less" : "expand_more"} className="shrink-0 text-muted-foreground" />
              </button>
              {open && (
                <div className="border-t border-border px-4 py-4">
                  <MatterDetail card={card} />
                </div>
              )}
            </div>
          );
        })}
      </div>
      {cards.length > shown.length && (
        <p className="mt-1.5 text-xs text-muted-foreground">and {cards.length - shown.length} more matters. Narrow the question to see them.</p>
      )}
    </section>
  );
}
