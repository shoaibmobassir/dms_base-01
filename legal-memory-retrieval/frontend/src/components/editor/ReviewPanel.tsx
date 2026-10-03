import { useMemo, useState } from "react";
import { Link } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import {
  applyReview,
  editErrorMessage,
  getContributors,
  getReview,
  type ReviewChange,
  type ReviewPerson,
} from "@/api/editor";
import { Button } from "@/components/ui/button";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const TYPE_LABEL: Record<string, string> = {
  insert: "Inserted",
  delete: "Deleted",
  move_from: "Moved from",
  move_to: "Moved to",
  format: "Formatted",
  paragraph_format: "Paragraph formatted",
  table_format: "Table formatted",
  section_format: "Section formatted",
  row_insert: "Row inserted",
  row_delete: "Row deleted",
  cell_insert: "Cell inserted",
  cell_delete: "Cell deleted",
};

// One colour per reviewer, stable across renders (Word does the same).
const PALETTE = ["#b45309", "#1d4ed8", "#047857", "#7c3aed", "#be123c", "#0e7490", "#4d7c0f", "#a21caf"];
export function authorColour(name: string) {
  let h = 0;
  for (const ch of name) h = (h * 31 + ch.charCodeAt(0)) >>> 0;
  return PALETTE[h % PALETTE.length];
}

const when = (iso: string | null) =>
  iso ? new Date(iso).toLocaleString(undefined, { day: "numeric", month: "short", year: "numeric", hour: "2-digit", minute: "2-digit" }) : "";

/** Word's reviewing pane: who changed what, and accepting or rejecting it (each action is a new version). */
export function ReviewPanel({
  documentId,
  baseVersionId,
  canWrite,
  onNewVersion,
  onJump,
}: {
  documentId: string;
  baseVersionId: string;
  /** This window holds the edit lock (accept/reject writes a version). */
  canWrite: boolean;
  onNewVersion: (versionNumber: number, note: string) => void;
  onJump?: (quote: string) => void;
}) {
  const { identityKey } = useApp();
  const review = useQuery({ queryKey: [identityKey, "doc-review", documentId, baseVersionId], queryFn: () => getReview(documentId) });
  const people = useQuery({ queryKey: [identityKey, "doc-contributors", documentId, baseVersionId], queryFn: () => getContributors(documentId) });
  const [person, setPerson] = useState<string>("");
  const [type, setType] = useState<string>("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const shown = useMemo(
    () => (review.data?.changes ?? []).filter((c) => (!person || c.author === person) && (!type || c.type === type)),
    [review.data, person, type],
  );
  const types = useMemo(() => [...new Set((review.data?.changes ?? []).map((c) => c.type))], [review.data]);

  const act = async (action: "accept" | "reject", body: { keys?: string[]; authors?: string[]; all?: boolean }) => {
    setBusy(true);
    setError(null);
    try {
      const out = await applyReview(documentId, { base_version_id: baseVersionId, action, ...body });
      onNewVersion(out.version_number, out.note);
    } catch (err) {
      setError(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  if (review.isPending) return <p className="p-4 text-sm text-muted-foreground">Reading the tracked changes…</p>;
  if (review.isError) return <p className="p-4 text-sm text-destructive">{editErrorMessage(review.error)}</p>;
  const r = review.data!;
  if (!r.word) return <p className="p-4 text-sm text-muted-foreground">Tracked changes apply to Word documents.</p>;
  const mayAct = r.can_review && canWrite;

  return (
    <div className="flex min-h-0 flex-col gap-3" data-testid="review-panel">
      <section className="rounded-lg border border-border bg-card p-4">
        <div className="mb-2 flex items-center justify-between">
          <span className="text-sm font-semibold">Who worked on it</span>
          <span className="text-xs text-muted-foreground">{r.total} pending change{r.total === 1 ? "" : "s"}</span>
        </div>
        <ul className="space-y-2" data-testid="review-people">
          {(people.data ?? []).map((p) => {
            const inFile = r.people.find((x) => x.author.toLowerCase() === p.name.toLowerCase());
            return (
              <li key={p.member_id ?? p.name} className="text-sm" data-testid="review-person">
                <div className="flex items-center gap-2">
                  <span className="h-2.5 w-2.5 shrink-0 rounded-full" style={{ background: authorColour(p.name) }} />
                  {p.member_id ? <Link to={`/people/${p.member_id}`} className="font-medium hover:underline">{p.name}</Link> : <span className="font-medium">{p.name}</span>}
                  {p.external && <span className="rounded bg-secondary px-1 text-xs uppercase text-muted-foreground">outside the firm</span>}
                  {inFile && (
                    <button type="button" className={cn("ml-auto text-xs underline", person === inFile.author ? "text-primary" : "text-muted-foreground")}
                      onClick={() => setPerson(person === inFile.author ? "" : inFile.author)} data-testid="review-filter-person">
                      {person === inFile.author ? "show everyone" : "only theirs"}
                    </button>
                  )}
                </div>
                <div className="pl-4 text-xs text-muted-foreground">
                  {summary(inFile, p.precentis)}
                  {p.last_at && <> · last {when(p.last_at)}</>}
                  {p.versions.length > 0 && <> · v{p.versions[0]}{p.versions.length > 1 ? `–v${p.versions[p.versions.length - 1]}` : ""}</>}
                </div>
              </li>
            );
          })}
        </ul>
        {Object.keys(r.outside_body).length > 0 && (
          <p className="mt-2 text-xs text-muted-foreground">
            Also changed in {Object.entries(r.outside_body).map(([k, n]) => `${k} (${n})`).join(", ")} — review those in Word.
          </p>
        )}
      </section>

      <section className="flex min-h-0 flex-1 flex-col rounded-lg border border-border bg-card">
        <div className="flex flex-wrap items-center gap-2 border-b border-border px-3 py-2">
          <select className="rounded border border-border bg-background px-1.5 py-1 text-xs" value={person} onChange={(e) => setPerson(e.target.value)}
            aria-label="Person" data-testid="review-person-select">
            <option value="">Everyone</option>
            {r.people.map((p) => <option key={p.author} value={p.author}>{p.author}</option>)}
          </select>
          <select className="rounded border border-border bg-background px-1.5 py-1 text-xs" value={type} onChange={(e) => setType(e.target.value)} aria-label="Kind">
            <option value="">All kinds</option>
            {types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t] ?? t}</option>)}
          </select>
          <span className="text-xs text-muted-foreground">{shown.length} shown</span>
          {mayAct && shown.length > 0 && (
            <span className="ml-auto flex gap-1">
              <Button size="sm" variant="outline" disabled={busy} data-testid="review-accept-shown"
                onClick={() => void act("accept", person && !type ? { authors: [person] } : { keys: shown.flatMap((c) => c.keys) })}>
                Accept {person && !type ? `all by ${person.split(" ")[0]}` : "shown"}
              </Button>
              <Button size="sm" variant="outline" disabled={busy} data-testid="review-reject-shown"
                onClick={() => void act("reject", person && !type ? { authors: [person] } : { keys: shown.flatMap((c) => c.keys) })}>
                Reject
              </Button>
            </span>
          )}
        </div>
        {!mayAct && r.can_review && <p className="px-3 pt-2 text-xs text-muted-foreground">Open the editor (someone else may be editing) to accept or reject.</p>}
        {error && <p className="px-3 pt-2 text-sm text-destructive" data-testid="review-error">{error}</p>}
        <ul className="min-h-0 flex-1 divide-y divide-border overflow-y-auto" data-testid="review-changes">
          {shown.length === 0 && <li className="p-3 text-sm text-muted-foreground">No pending tracked changes{person ? ` by ${person}` : ""}.</li>}
          {shown.map((c) => (
            <ChangeRow key={c.id} change={c} busy={busy} mayAct={mayAct} onJump={onJump}
              onAccept={() => void act("accept", { keys: c.keys })} onReject={() => void act("reject", { keys: c.keys })} />
          ))}
        </ul>
      </section>
    </div>
  );
}

function summary(p: ReviewPerson | undefined, precentis: Record<string, number>) {
  const parts: string[] = [];
  if (p) {
    if (p.insertions) parts.push(`${p.insertions} insertion${p.insertions === 1 ? "" : "s"} (+${p.words_added} words)`);
    if (p.deletions) parts.push(`${p.deletions} deletion${p.deletions === 1 ? "" : "s"} (−${p.words_removed})`);
    if (p.formats) parts.push(`${p.formats} formatting`);
    if (p.moves) parts.push(`${p.moves} move${p.moves === 1 ? "" : "s"}`);
    if (p.comments || p.replies) parts.push(`${p.comments} comment${p.comments === 1 ? "" : "s"}, ${p.replies} repl${p.replies === 1 ? "y" : "ies"}`);
  }
  const saves = precentis["edit.save"] ?? 0;
  const uploads = precentis["version.upload"] ?? 0;
  const reviews = (precentis["review.accept"] ?? 0) + (precentis["review.reject"] ?? 0);
  if (saves) parts.push(`${saves} save${saves === 1 ? "" : "s"} here`);
  if (uploads) parts.push(`${uploads} upload${uploads === 1 ? "" : "s"}`);
  if (reviews) parts.push(`${reviews} review${reviews === 1 ? "" : "s"}`);
  return parts.join(" · ") || "No pending changes";
}

function ChangeRow({ change: c, busy, mayAct, onAccept, onReject, onJump }: {
  change: ReviewChange; busy: boolean; mayAct: boolean; onAccept: () => void; onReject: () => void; onJump?: (quote: string) => void;
}) {
  const text = c.texts.join(" … ");
  const inserted = c.type === "insert" || c.type === "move_to" || c.type === "row_insert";
  const deleted = c.type === "delete" || c.type === "move_from" || c.type === "row_delete";
  const jumpTo = (inserted ? c.texts[0] : c.context || c.texts[0] || "").slice(0, 80);
  return (
    <li className="group p-3 text-sm" data-testid="review-change" data-author={c.author} data-type={c.type}>
      <div className="flex items-center gap-2 text-xs">
        <span className="h-2 w-2 shrink-0 rounded-full" style={{ background: authorColour(c.author) }} />
        <span className="font-semibold text-foreground">{c.author}</span>
        <span className="text-muted-foreground">{TYPE_LABEL[c.type] ?? c.type}{c.paragraph ? " (paragraph)" : ""}{c.table ? " · table" : ""}</span>
        <span className="ml-auto text-muted-foreground">{when(c.date)}</span>
      </div>
      <button type="button" className="mt-1 block w-full text-left" onClick={() => jumpTo && onJump?.(jumpTo)} disabled={!onJump || !jumpTo}>
        {text ? (
          <span className={cn("line-clamp-3 whitespace-pre-wrap",
            inserted && "text-success-ink underline decoration-success",
            deleted && "text-destructive line-through")}>{text}</span>
        ) : null}
        {c.detail && <span className="block text-xs text-muted-foreground">{c.detail}</span>}
        {!text && c.context && <span className="line-clamp-2 block text-xs italic text-muted-foreground">in “{c.context}”</span>}
      </button>
      {mayAct && (
        <div className="mt-1 flex gap-1 opacity-70 transition-opacity group-hover:opacity-100">
          <button type="button" disabled={busy} onClick={onAccept} className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs hover:bg-secondary"
            data-testid="review-accept">
            <Icon name="check" style={{ fontSize: 14 }} /> Accept
          </button>
          <button type="button" disabled={busy} onClick={onReject} className="inline-flex items-center gap-0.5 rounded px-1.5 py-0.5 text-xs hover:bg-secondary"
            data-testid="review-reject">
            <Icon name="close" style={{ fontSize: 14 }} /> Reject
          </button>
        </div>
      )}
    </li>
  );
}
