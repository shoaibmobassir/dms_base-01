import { Fragment, createContext, useContext, type ReactNode } from "react";
import { Link } from "react-router-dom";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { useDocumentPanel } from "@/components/ai/DocumentPanelDrawer";
import { useApp } from "@/context/AppContext";
import type { AskResult, Citation } from "@/api/types";
import { citationChipClass } from "@/components/common/citation";
import { Markdown } from "@/components/chat/Markdown";

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

type AnswerPerson = { member_id: string; name: string; role?: string; office?: string; role_on_matter?: string };
type ResolvedScope = { kind?: string; label?: string; method?: string };

function scopeMethodLabel(method?: string): string {
  if (!method) return "";
  if (method.startsWith("resolver")) return "Matter identified from your description";
  if (method.includes("client")) return "All matters for this client";
  return "Scope you selected";
}

/** People the answer is about (ranked people results). Matter teams are shown in the matter brief. */
function answerPeople(result: AskResult): AnswerPerson[] {
  return (result.people as AnswerPerson[] | undefined) ?? [];
}

function str(v: unknown): string | undefined {
  return v === null || v === undefined || v === "" ? undefined : String(v);
}

/** Open a document in the side panel, highlighting its verified quotes when the answer has them. */
function useOpenCitedDocument(result?: AskResult) {
  const panel = useDocumentPanel();
  return (documentId: string) => {
    const span = (result?.span_citations ?? []).find((c) => String(c.document_id ?? "") === documentId);
    if (span) return panel?.openCitation(span);
    const src = result ? citedSources(result).find((s) => s.document_id === documentId) : undefined;
    panel?.openDocument(documentId, { title: src?.title, snippet: src?.snippet });
  };
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
// ids for uploads), matter records (MTR-2026-00901 or MTR-CI-OPEN-001) and people.
const EVIDENCE_ID = String.raw`DOC-(?:\d+|[0-9A-F]{8,})|MTR-(?:\d{4}-\d+|[A-Z]+(?:-[A-Z]+)*-\d+)|MEM-\d+`;
const CITE_GROUP_RE = new RegExp(String.raw`[(\[]\s*((?:${EVIDENCE_ID})(?:\s*[,;]\s*(?:${EVIDENCE_ID}))*)\s*[)\]]|(${EVIDENCE_ID})`, "gi");
const EVIDENCE_ID_RE = new RegExp(EVIDENCE_ID, "gi");

const CHIP =
  "mx-0.5 inline-flex items-center rounded-[3px] bg-wine-soft px-1 align-baseline font-mono-id text-xs font-semibold text-wine transition-colors hover:bg-wine hover:text-primary-foreground";

/** Names for the ids in the answer, so chips read "Share Purchase Agreement" or "Helena Voss" instead of an id. */
const DocTitles = createContext<Map<string, string>>(new Map());

function shortTitle(title: string) {
  return title.replace(/\.(docx?|pdf|txt|xlsx?|pptx?)$/i, "").replace(/[_]+/g, " ").trim();
}

function CitationChip({ id, onCite }: { id: string; onCite: (documentId: string) => void }) {
  const titles = useContext(DocTitles);
  const upper = id.toUpperCase();
  if (upper.startsWith("MTR-")) {
    return (
      <Link to={`/matters/${upper}`} className={CHIP} data-testid={`citation-${upper}`} title={`Matter record ${upper}`}>
        {titles.get(upper) ?? upper}
      </Link>
    );
  }
  if (upper.startsWith("MEM-")) {
    return (
      <Link to={`/people/${upper}`} className={`${CHIP} font-sans`} data-testid={`citation-${upper}`} title={`Firm member ${upper}`}>
        {titles.get(upper) ?? upper}
      </Link>
    );
  }
  return (
    <button
      type="button"
      onClick={() => onCite(upper)}
      className={`${CHIP} max-w-[240px] truncate font-sans`}
      data-testid={`citation-${upper}`}
      title={titles.get(upper) ? `${titles.get(upper)} (${upper})` : upper}
    >
      {titles.get(upper) ? shortTitle(titles.get(upper)!) : upper}
    </button>
  );
}

/** Verified span citations behind the answer's [n] markers, and how to open one. */
export type SpanCites = { byRef: Map<number, Citation>; open: (c: Citation) => void };

const SPAN_REF_RE = /\[(\d{1,3})\]/g;

function SpanChip({ num, citation, onOpen }: { num: number; citation: Citation; onOpen: () => void }) {
  const partial = citation.support === "partial";
  return (
    <button
      type="button"
      onClick={onOpen}
      className={citationChipClass({ partial })}
      data-testid={`span-citation-${num}`}
      title={`${citation.title ?? citation.document_id ?? "Source"}${partial ? " — supports only part of this statement" : ""}`}
    >
      [{num}]
    </button>
  );
}

function withSpanChips(text: string, spans: SpanCites | undefined, keyBase: number): ReactNode[] {
  if (!spans) return [<Fragment key={keyBase}>{text}</Fragment>];
  const out: ReactNode[] = [];
  let last = 0;
  let key = keyBase;
  for (const m of text.matchAll(SPAN_REF_RE)) {
    const citation = spans.byRef.get(Number(m[1]));
    if (!citation) continue;
    const start = m.index ?? 0;
    if (start > last) out.push(<Fragment key={key++}>{text.slice(last, start)}</Fragment>);
    out.push(<SpanChip key={key++} num={Number(m[1])} citation={citation} onOpen={() => spans.open(citation)} />);
    last = start + m[0].length;
  }
  if (last < text.length) out.push(<Fragment key={key++}>{text.slice(last)}</Fragment>);
  return out;
}

/**
 * Render DOC / MTR / MEM references (bare or in "(A, B)" groups) and [n] span markers as chips.
 * With `seenMatters`, a matter record is shown the first time only: answers cite it after every
 * line ("… (MTR-2026-00901)"), which repeats what the matter brief already says.
 */
export function withCitationChips(
  text: string,
  onCite: (documentId: string) => void,
  spans?: SpanCites,
  seenMatters?: Set<string>,
): ReactNode[] {
  const out: ReactNode[] = [];
  let last = 0;
  let key = 0;
  for (const m of text.matchAll(CITE_GROUP_RE)) {
    const start = m.index ?? 0;
    const ids = ((m[1] ?? m[2] ?? "").match(EVIDENCE_ID_RE) ?? []).filter((id) => {
      const upper = id.toUpperCase();
      if (!seenMatters || !upper.startsWith("MTR-")) return true;
      if (seenMatters.has(upper)) return false;
      seenMatters.add(upper);
      return true;
    });
    // A group of hidden repeats disappears with the space in front of it.
    const before = ids.length ? text.slice(last, start) : text.slice(last, start).replace(/\s+$/, "");
    if (before) {
      const parts = withSpanChips(before, spans, key);
      key += parts.length;
      out.push(...parts);
    }
    for (const id of ids) out.push(<CitationChip key={key++} id={id} onCite={onCite} />);
    last = start + m[0].length;
  }
  if (last < text.length) out.push(...withSpanChips(text.slice(last), spans, key));
  return out;
}

/** The answer text: the same Markdown as the Assistant (lists, tables, bold), with record ids and [n] markers as chips. */
export function AnswerBody({ text, onCite, spans }: { text: string; onCite: (documentId: string) => void; spans?: SpanCites }) {
  const seenMatters = new Set<string>();
  return (
    <Markdown
      text={text}
      preserveLineBreaks
      paragraphClassName="my-0 whitespace-pre-wrap text-[16px] leading-[1.75] text-foreground"
      renderCitation={(n) => {
        const citation = spans?.byRef.get(n);
        return citation ? <SpanChip num={n} citation={citation} onOpen={() => spans!.open(citation)} /> : <>[{n}]</>;
      }}
      renderText={(t) => withCitationChips(t, onCite, undefined, seenMatters)}
    />
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
  const panel = useDocumentPanel();
  const openDoc = useOpenCitedDocument(result);

  const status = String(result.status ?? "");
  const answer = String(result.answer ?? "").trim();
  const spanList = result.span_citations ?? [];
  const spans: SpanCites | undefined = spanList.length
    ? {
        byRef: new Map(spanList.filter((c) => typeof c.ref === "number").map((c) => [c.ref as number, c])),
        open: (c) => panel?.openCitation(c),
      }
    : undefined;
  const removed = result.grounding?.removed ?? 0;

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
    ? "Assembled from retrieved passages: no written answer could be checked against the sources."
    : provider === "records"
      ? "Assembled from the firm's matter records: the written answer was unavailable."
      : provider
        ? "Written from the firm's records cited above. Check the sources before relying on it."
        : "";
  const titles = new Map<string, string>();
  for (const src of citedSources(result)) titles.set(src.document_id.toUpperCase(), src.title);
  for (const c of spanList) if (c.document_id && c.title) titles.set(String(c.document_id).toUpperCase(), String(c.title));
  for (const m of result.matter_cards ?? []) {
    titles.set(m.matter_id.toUpperCase(), m.matter_code);
    for (const p of m.team ?? []) titles.set(p.member_id.toUpperCase(), p.name);
  }
  for (const p of (result.people as AnswerPerson[] | undefined) ?? []) titles.set(p.member_id.toUpperCase(), p.name);

  return (
    <DocTitles.Provider value={titles}>
    <div className="space-y-8" data-testid="ai-answer">
      {result.key_finding && (
        <div className="rounded-lg border border-wine/30 bg-wine-soft/40 p-5">
          <div className="meta-label mb-1 text-wine">Key finding</div>
          <p className="font-display text-xl leading-snug text-ink">{withCitationChips(String(result.key_finding), openDoc, spans)}</p>
        </div>
      )}
      {status === "insufficient" && (
        <p className="rounded-md border border-border bg-secondary/50 px-3 py-2 text-sm text-muted-foreground" data-testid="ai-partial">
          The records found concern this matter but do not fully answer the question.
        </p>
      )}
      <AnswerBody text={answer} onCite={openDoc} spans={spans} />
      {removed > 0 && (
        <p className="rounded-md border border-border bg-secondary/50 px-3 py-2 text-sm text-muted-foreground" data-testid="ai-grounding-removed">
          {removed === 1 ? "1 statement was" : `${removed} statements were`} removed because the cited sources did not
          support {removed === 1 ? "it" : "them"}.
        </p>
      )}
      {caption && <p className="text-xs text-muted-foreground" data-testid="ai-provider">{caption}</p>}
    </div>
    </DocTitles.Provider>
  );
}

/** Plain text of an answer for pasting into an email or note: the text, then the sources its [n] markers point to. */
export function answerAsText(result: AskResult): string {
  const lines = [String(result.key_finding ?? "").trim(), String(result.answer ?? "").trim()].filter(Boolean);
  const refs = (result.span_citations ?? [])
    .filter((c) => typeof c.ref === "number")
    .map((c) => `[${c.ref}] ${c.title ?? c.document_id ?? "Source"}${c.page != null ? `, p. ${String(c.page)}` : ""}`);
  return refs.length ? `${lines.join("\n\n")}\n\nSources\n${refs.join("\n")}` : lines.join("\n\n");
}

/** Copy the answer, copy a link to it, or carry on in the Assistant. */
export function AnswerActions({ result, question }: { result: AskResult; question: string }) {
  const { toast } = useApp();
  const copy = async (text: string, done: string) => {
    try {
      await navigator.clipboard.writeText(text);
      toast(done);
    } catch {
      toast("Copying was blocked by the browser");
    }
  };
  const top = result.panel?.matters?.[0];
  const assistant = `/chat?${new URLSearchParams({ ...(top ? { matter: top.matter_id } : {}), q: question }).toString()}`;
  const btn = "inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-xs font-medium text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground";
  return (
    <div className="flex flex-wrap items-center gap-1 border-t border-border pt-3" data-testid="answer-actions">
      <button type="button" className={btn} onClick={() => void copy(answerAsText(result), "Answer copied with its sources")} data-testid="answer-copy">
        <Icon name="content_copy" style={{ fontSize: 16 }} /> Copy answer
      </button>
      <button type="button" className={btn} onClick={() => void copy(window.location.href, "Link copied")} data-testid="answer-copy-link">
        <Icon name="link" style={{ fontSize: 16 }} /> Copy link
      </button>
      <Link to={assistant} className={btn} data-testid="answer-assistant">
        <Icon name="edit_note" style={{ fontSize: 16 }} /> Continue in the Assistant
      </Link>
    </div>
  );
}

/** The answer while the model is still writing (replaced by AIAnswer when final). */
export function AIStreaming({ keyFinding, text, verifying = false }: { keyFinding: string; text: string; verifying?: boolean }) {
  const openDoc = useOpenCitedDocument();
  return (
    <div className="space-y-8" data-testid="ai-streaming" aria-busy="true">
      <div className="flex items-center gap-2 text-xs text-muted-foreground" role="status" data-testid="ai-draft-banner">
        <span className="h-2 w-2 animate-pulse rounded-full bg-wine" />
        {verifying
          ? "Draft — checking each statement against its source before it is shown…"
          : "Draft — statements are checked against their sources when the answer is complete."}
      </div>
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

/** Document ids the answer cites: its citation list, verified spans and ids in the text. */
function answerDocumentIds(result: AskResult): Set<string> {
  const ids = new Set<string>();
  for (const c of (result.citations as unknown[] | undefined) ?? []) if (typeof c === "string") ids.add(c.toUpperCase());
  for (const c of result.span_citations ?? []) if (c.document_id) ids.add(String(c.document_id).toUpperCase());
  for (const t of [result.answer, result.key_finding]) {
    for (const id of String(t ?? "").match(EVIDENCE_ID_RE) ?? []) ids.add(id.toUpperCase());
  }
  return ids;
}

function SourceList({
  label,
  items,
  onOpen,
  testId,
  muted,
}: {
  label: string;
  items: CitedSource[];
  onOpen: (documentId: string) => void;
  testId: string;
  muted?: boolean;
}) {
  return (
    <div>
      <SectionLabel>
        {label} ({items.length})
      </SectionLabel>
      <ul className="space-y-3" data-testid={testId}>
        {items.map((s) => (
          <li key={s.document_id}>
            <button type="button" onClick={() => onOpen(s.document_id)} className="block w-full text-left" title={s.document_id}>
              <span className={`block text-sm hover:text-wine ${muted ? "text-foreground/75" : "text-foreground"}`}>{s.title}</span>
              <span className="block text-xs text-muted-foreground">{[s.document_type, s.matter_code].filter(Boolean).join(" · ")}</span>
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Right-hand context column: scope, people and the sources, cited first. */
export function AnswerContext({ result, withPanel = false }: { result: AskResult; withPanel?: boolean }) {
  const openDoc = useOpenCitedDocument(result);
  const sources = citedSources(result);
  const people = answerPeople(result);
  // Documents the answer actually cites come first; the rest were retrieved but not used.
  const citedIds = answerDocumentIds(result);
  const cited = sources.filter((s) => citedIds.has(s.document_id.toUpperCase()));
  const searched = sources.filter((s) => !citedIds.has(s.document_id.toUpperCase()));
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
      {people.length > 0 && !withPanel && (
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
      {withPanel ? null : sources.length === 0 ? (
        <div>
          <SectionLabel>Sources (0)</SectionLabel>
          <p className="text-sm text-muted-foreground">No sources.</p>
        </div>
      ) : (
        <>
          {cited.length > 0 && <SourceList label="Cited in the answer" testId="answer-sources" items={cited} onOpen={openDoc} />}
          {searched.length > 0 && (
            <SourceList
              label="Also searched"
              testId={cited.length ? "answer-sources-searched" : "answer-sources"}
              items={searched}
              onOpen={openDoc}
              muted={cited.length > 0}
            />
          )}
        </>
      )}
      <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
        <Icon name="visibility_lock" style={{ fontSize: 14 }} /> Only records within your access scope were searched.
      </p>
    </div>
  );
}
