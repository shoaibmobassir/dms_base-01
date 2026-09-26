import { Fragment, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { useInspector } from "@/components/common/Inspector";
import type { AskResult } from "@/api/types";

/** A passage the answer relies on (from `sources` in the /api/answers payload). */
export type CitedSource = {
  document_id: string;
  chunk_id?: string;
  title: string;
  document_type?: string;
  matter_id?: string;
  matter_code?: string;
  snippet?: string;
};

type MatchedMatter = { matter_id: string; matter_code: string; title: string; client_name?: string; court?: string };
type AnswerPerson = { member_id: string; name: string; role?: string; office?: string; role_on_matter?: string };
type ResolvedScope = { kind?: string; label?: string; method?: string };

function scopeMethodLabel(method?: string): string {
  if (!method) return "";
  if (method.startsWith("resolver")) return "Matter identified from your description";
  if (method.includes("client")) return "All matters for this client";
  return "Scope you selected";
}

/** People the answer is about: ranked people results, else the teams of the matters in scope. */
function answerPeople(result: AskResult): AnswerPerson[] {
  const direct = (result.people as AnswerPerson[] | undefined) ?? [];
  if (direct.length) return direct;
  const cards = (result.matter_cards as { team?: AnswerPerson[] }[] | undefined) ?? [];
  if (cards.length !== 1) return [];
  return cards[0].team ?? [];
}

function str(v: unknown): string | undefined {
  return v === null || v === undefined || v === "" ? undefined : String(v);
}

export function citedSources(result: AskResult): CitedSource[] {
  const seen = new Set<string>();
  const out: CitedSource[] = [];
  for (const raw of [...(result.sources ?? []), ...(result.structured_citations ?? [])]) {
    const document_id = str(raw.document_id);
    if (!document_id || seen.has(document_id)) continue;
    seen.add(document_id);
    out.push({
      document_id,
      chunk_id: str(raw.chunk_id),
      title: str(raw.title) ?? document_id,
      document_type: str(raw.document_type),
      matter_id: str(raw.matter_id),
      matter_code: str(raw.matter_code),
      snippet: str(raw.snippet),
    });
  }
  return out;
}

// Evidence ids the Ask-the-Firm answer cites: documents (numeric corpus ids or hex
// ids for uploads), matter records and people.
const EVIDENCE_ID = String.raw`DOC-(?:\d+|[0-9A-F]{8,})|MTR-\d{4}-\d+|MEM-\d+`;
const CITE_GROUP_RE = new RegExp(String.raw`[(\[]\s*((?:${EVIDENCE_ID})(?:\s*[,;]\s*(?:${EVIDENCE_ID}))*)\s*[)\]]|(${EVIDENCE_ID})`, "gi");
const EVIDENCE_ID_RE = new RegExp(EVIDENCE_ID, "gi");

const CHIP =
  "mx-0.5 inline-flex items-center rounded-[3px] bg-wine-soft px-1 align-baseline font-mono-id text-[11px] font-semibold text-wine transition-colors hover:bg-wine hover:text-primary-foreground";

function CitationChip({ id, onCite }: { id: string; onCite: (documentId: string) => void }) {
  const upper = id.toUpperCase();
  if (upper.startsWith("MTR-")) {
    return (
      <Link to={`/matters/${upper}`} className={CHIP} data-testid={`citation-${upper}`} title="Matter record">
        {upper}
      </Link>
    );
  }
  if (upper.startsWith("MEM-")) {
    return (
      <Link to={`/people/${upper}`} className={CHIP} data-testid={`citation-${upper}`} title="Firm member">
        {upper}
      </Link>
    );
  }
  return (
    <button type="button" onClick={() => onCite(upper)} className={CHIP} data-testid={`citation-${upper}`}>
      {upper}
    </button>
  );
}

/** Render DOC / MTR / MEM references (bare or in "(A, B)" groups) as citation chips. */
export function withCitationChips(text: string, onCite: (documentId: string) => void): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(CITE_GROUP_RE)) {
    const start = m.index ?? 0;
    if (start > last) out.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>);
    for (const id of (m[1] ?? m[2] ?? "").match(EVIDENCE_ID_RE) ?? []) {
      out.push(<CitationChip key={key++} id={id} onCite={onCite} />);
    }
    last = start + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return out;
}

/** Minimal markdown: paragraphs, "- " bullet lists and "#" headings, with citation chips inline. */
export function AnswerBody({ text, onCite }: { text: string; onCite: (documentId: string) => void }) {
  const blocks = text.replace(/\r/g, "").split(/\n{2,}/).map((b) => b.trim()).filter(Boolean);
  const inline = (t: string) => withCitationChips(t.replace(/\*\*(.+?)\*\*/g, "$1"), onCite);
  return (
    <div className="space-y-4 text-[16px] leading-[1.75] text-foreground">
      {blocks.map((block, i) => {
        const lines = block.split("\n");
        const heading = block.match(/^#{1,4}\s+(.*)$/);
        if (heading && lines.length === 1) {
          return <h3 key={i} className="font-display text-lg text-ink">{inline(heading[1])}</h3>;
        }
        const items = lines.filter((l) => /^\s*[-*•]\s+/.test(l));
        if (items.length > 0) {
          const lead = lines.filter((l) => !/^\s*[-*•]\s+/.test(l)).join(" ").trim();
          return (
            <div key={i}>
              {lead && <p className="mb-2">{inline(lead)}</p>}
              <ul className="list-disc space-y-1 pl-6">
                {items.map((l, j) => <li key={j}>{inline(l.replace(/^\s*[-*•]\s+/, ""))}</li>)}
              </ul>
            </div>
          );
        }
        return <p key={i} className="whitespace-pre-wrap">{inline(block)}</p>;
      })}
    </div>
  );
}

export function AIAssembling({ label = "Searching the firm's records within your access scope…" }: { label?: string }) {
  return (
    <div className="flex items-center gap-3 py-6 text-sm text-muted-foreground" data-testid="ai-assembling" role="status">
      <span className="h-2 w-2 animate-pulse rounded-full bg-wine" />
      {label}
    </div>
  );
}

export function AIAnswer({ result }: { result: AskResult }) {
  const inspector = useInspector();
  const sources = citedSources(result);
  const openDoc = (documentId: string) => {
    const src = sources.find((s) => s.document_id === documentId);
    inspector?.open({ type: "document", id: documentId, chunkId: src?.chunk_id });
  };

  const status = String(result.status ?? "");
  const answer = String(result.answer ?? "").trim();

  if (result.abstained && (status === "not_found" || result.reason === "scope_not_found") && answer) {
    return (
      <div className="space-y-4 rounded-lg border border-border bg-card p-6" data-testid="ai-not-found">
        <div className="eyebrow text-muted-foreground">No matching matter</div>
        <AnswerBody text={answer} onCite={openDoc} />
      </div>
    );
  }

  if (result.abstained) {
    return (
      <div className="rounded-lg border border-border bg-card p-6" data-testid="ai-abstained">
        <div className="eyebrow text-muted-foreground">No grounded answer</div>
        <p className="mt-2 text-[15px] leading-relaxed">
          The firm's records you can access don't support an answer to this question
          {result.reason ? ` (${String(result.reason).replace(/_/g, " ")})` : ""}. Try naming the matter, party or forum.
        </p>
      </div>
    );
  }

  const provider = String(result.provider ?? "");
  const caption = provider.startsWith("extractive")
    ? "Assembled from retrieved passages (the language model did not produce a grounded answer)."
    : provider === "records"
      ? "Assembled from the firm's matter records (the language model was unavailable)."
      : provider
        ? `Generated by ${provider} from the firm's records and passages cited above.`
        : "";

  return (
    <div className="space-y-8" data-testid="ai-answer">
      {result.key_finding && (
        <div className="rounded-lg border border-wine/30 bg-wine-soft/40 p-5">
          <div className="meta-label mb-1 text-wine">Key finding</div>
          <p className="font-display text-xl leading-snug text-ink">{withCitationChips(String(result.key_finding), openDoc)}</p>
        </div>
      )}
      {status === "insufficient" && (
        <p className="rounded-md border border-border bg-secondary/50 px-3 py-2 text-sm text-muted-foreground" data-testid="ai-partial">
          The records found concern this matter but do not fully answer the question.
        </p>
      )}
      <AnswerBody text={answer} onCite={openDoc} />
      {caption && <p className="text-xs text-muted-foreground" data-testid="ai-provider">{caption}</p>}
    </div>
  );
}

/** The answer while the model is still writing (replaced by AIAnswer when final). */
export function AIStreaming({ keyFinding, text }: { keyFinding: string; text: string }) {
  const inspector = useInspector();
  const openDoc = (documentId: string) => inspector?.open({ type: "document", id: documentId });
  return (
    <div className="space-y-8" data-testid="ai-streaming" aria-busy="true">
      {keyFinding && (
        <div className="rounded-lg border border-wine/30 bg-wine-soft/40 p-5">
          <div className="meta-label mb-1 text-wine">Key finding</div>
          <p className="font-display text-xl leading-snug text-ink">{withCitationChips(keyFinding, openDoc)}</p>
        </div>
      )}
      {text ? <AnswerBody text={text} onCite={openDoc} /> : <AIAssembling label="Writing the answer…" />}
    </div>
  );
}

/** Right-hand context column: the cited sources and the matters they come from. */
export function AnswerContext({ result }: { result: AskResult }) {
  const inspector = useInspector();
  const sources = citedSources(result);
  const matters = (result.matchedMatters as MatchedMatter[] | undefined) ?? [];
  const people = answerPeople(result);
  const scope = result.resolved_scope as ResolvedScope | null | undefined;

  return (
    <div className="space-y-8">
      {scope && scope.label && (
        <div data-testid="answer-scope">
          <SectionLabel>Answered for</SectionLabel>
          <p className="text-sm text-foreground">{scope.label}</p>
          <p className="text-xs text-muted-foreground">{scopeMethodLabel(scope.method)}</p>
        </div>
      )}
      {people.length > 0 && (
        <div>
          <SectionLabel>People ({people.length})</SectionLabel>
          <ul className="space-y-2" data-testid="answer-people">
            {people.map((p) => (
              <li key={p.member_id}>
                <Link to={`/people/${p.member_id}`} className="group block">
                  <span className="block text-sm group-hover:text-wine">{p.name}</span>
                  <span className="block text-xs text-muted-foreground">
                    {[p.role, p.role_on_matter, p.office].filter(Boolean).join(" · ")}
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <div>
        <SectionLabel>Sources ({sources.length})</SectionLabel>
        {sources.length === 0 ? (
          <p className="text-sm text-muted-foreground">No sources.</p>
        ) : (
          <ul className="space-y-3" data-testid="answer-sources">
            {sources.map((s) => (
              <li key={s.document_id}>
                <button
                  type="button"
                  onClick={() => inspector?.open({ type: "document", id: s.document_id, chunkId: s.chunk_id })}
                  className="block w-full text-left"
                >
                  <span className="font-mono-id text-[11px] text-wine">{s.document_id}</span>
                  <span className="block text-sm text-foreground hover:text-wine">{s.title}</span>
                  <span className="block text-xs text-muted-foreground">{[s.document_type, s.matter_code].filter(Boolean).join(" · ")}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      {matters.length > 0 && (
        <div>
          <SectionLabel>Matters</SectionLabel>
          <ul className="space-y-3">
            {matters.map((m) => (
              <li key={m.matter_id}>
                <Link to={`/matters/${m.matter_id}`} className="group block">
                  <span className="font-mono-id text-[11px] text-muted-foreground">{m.matter_code}</span>
                  <span className="block text-sm group-hover:text-wine">{m.client_name ?? m.title}</span>
                  {m.court && <span className="block text-xs text-muted-foreground">{m.court}</span>}
                </Link>
              </li>
            ))}
          </ul>
        </div>
      )}
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Icon name="visibility_lock" style={{ fontSize: 14 }} /> Only records within your access scope were searched.
      </p>
    </div>
  );
}
