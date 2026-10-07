import { useEffect, useMemo, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import {
  FORMAT_LABEL,
  addColumns,
  addRows,
  createReview,
  usePresets,
  useReviews,
  type AnswerFormat,
  type ColumnInput,
  type Review,
} from "@/api/tabular";
import { useWorkspaceItems, type WorkspaceDocument, type WorkspaceKind } from "@/api/workspaces";
import { Field, fieldControl } from "@/components/common/Field";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

type Custom = { label: string; question: string; answer_format: AnswerFormat; choices: string };
const EMPTY_CUSTOM: Custom = { label: "", question: "", answer_format: "text", choices: "" };

/** Pick ready-made questions and write your own. */
function ColumnPicker({ presets, setPresets, customs, setCustoms }: {
  presets: Set<string>; setPresets: (s: Set<string>) => void; customs: Custom[]; setCustoms: (c: Custom[]) => void;
}) {
  const all = usePresets();
  return (
    <div className="space-y-3">
      <div>
        <div className="mb-1.5 text-xs font-medium text-muted-foreground">Common questions</div>
        <div className="flex flex-wrap gap-1.5">
          {(all.data ?? []).map((p) => {
            const on = presets.has(p.key);
            return (
              <button key={p.key} type="button" aria-pressed={on} title={p.question}
                onClick={() => { const n = new Set(presets); if (on) n.delete(p.key); else n.add(p.key); setPresets(n); }}
                className={cn("rounded-full border px-2.5 py-1 text-xs", on ? "border-wine bg-wine-soft text-wine" : "border-border hover:bg-secondary")}
                data-testid="review-preset">
                {p.label}
              </button>
            );
          })}
        </div>
      </div>
      <div className="space-y-2">
        <div className="text-xs font-medium text-muted-foreground">Your own questions</div>
        {customs.map((c, i) => (
          <div key={i} className="grid grid-cols-[1fr_2fr_auto_auto] items-start gap-1.5">
            <input value={c.label} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, label: e.target.value } : x)))}
              placeholder="Column name" maxLength={120} className={fieldControl} aria-label="Column name" data-testid="review-custom-label" />
            <input value={c.question} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, question: e.target.value } : x)))}
              placeholder="Question to answer for every document" maxLength={2000} className={fieldControl} aria-label="Question" data-testid="review-custom-question" />
            <select value={c.answer_format} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, answer_format: e.target.value as AnswerFormat } : x)))}
              className="h-9 rounded-md border border-border bg-card px-2 text-sm" aria-label="Answer as">
              {Object.entries(FORMAT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
            </select>
            <button type="button" aria-label="Remove question" className="h-9 rounded p-1 text-muted-foreground hover:bg-secondary"
              onClick={() => setCustoms(customs.filter((_, j) => j !== i))}>
              <Icon name="close" style={{ fontSize: 16 }} />
            </button>
            {c.answer_format === "choice" && (
              <input value={c.choices} onChange={(e) => setCustoms(customs.map((x, j) => (j === i ? { ...x, choices: e.target.value } : x)))}
                placeholder="Choices, separated by commas" className={cn(fieldControl, "col-span-4")} aria-label="Choices" />
            )}
          </div>
        ))}
        <Button type="button" variant="ghost" size="sm" onClick={() => setCustoms([...customs, { ...EMPTY_CUSTOM }])} data-testid="review-add-custom">
          <Icon name="add" style={{ fontSize: 16 }} /> Add a question
        </Button>
      </div>
    </div>
  );
}

function columnsFrom(presets: Set<string>, customs: Custom[]): ColumnInput[] {
  return [
    ...[...presets].map((preset) => ({ preset })),
    ...customs.filter((c) => c.label.trim() && c.question.trim()).map((c) => ({
      label: c.label.trim(), question: c.question.trim(), answer_format: c.answer_format,
      choices: c.choices.split(",").map((x) => x.trim()).filter(Boolean),
    })),
  ];
}

/** Choose the rows: documents of this workspace, or its folders. */
function RowPicker({ kind, id, groupBy, selected, setSelected, open, exclude }: {
  kind: WorkspaceKind; id: string; groupBy: "document" | "folder"; selected: Set<string>; setSelected: (s: Set<string>) => void;
  open: boolean; exclude?: Set<string>;
}) {
  const items = useWorkspaceItems(kind, id, { recursive: true, enabled: open });
  const [q, setQ] = useState("");
  const docs = (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted && !exclude?.has(d.document_id));
  const folders = useMemo(() => {
    const set = new Set<string>();
    for (const d of docs) {
      const parts = (d.folder || "").split("/").filter(Boolean);
      for (let i = 1; i <= parts.length; i++) set.add(parts.slice(0, i).join("/"));
    }
    return [...set].filter((f) => !exclude?.has(f)).sort();
  }, [docs, exclude]);
  const list = groupBy === "folder" ? folders.map((f) => ({ key: f, label: f, hint: "" }))
    : docs.map((d) => ({ key: d.document_id, label: d.title, hint: d.folder }));
  const shown = list.filter((x) => !q || x.label.toLowerCase().includes(q.toLowerCase()));
  const toggle = (k: string) => { const n = new Set(selected); if (n.has(k)) n.delete(k); else n.add(k); setSelected(n); };
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={groupBy === "folder" ? "Find a folder" : "Find a document"}
          className={fieldControl} aria-label="Filter" />
        <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set(shown.map((x) => x.key)))}>All</Button>
        <Button type="button" variant="ghost" size="sm" onClick={() => setSelected(new Set())}>None</Button>
      </div>
      <ul className="max-h-56 divide-y divide-border overflow-y-auto rounded-md border border-border" data-testid="review-row-picker">
        {items.isPending && <li className="px-3 py-2 text-xs text-muted-foreground">Loading…</li>}
        {!items.isPending && shown.length === 0 && (
          <li className="px-3 py-2 text-xs text-muted-foreground">{groupBy === "folder" ? "No folders here yet." : "No documents here yet."}</li>
        )}
        {shown.map((x) => (
          <li key={x.key}>
            <label className="flex cursor-pointer items-center gap-2 px-3 py-1.5 text-sm hover:bg-secondary/60">
              <input type="checkbox" checked={selected.has(x.key)} onChange={() => toggle(x.key)} />
              <Icon name={groupBy === "folder" ? "folder" : "description"} className="text-muted-foreground" style={{ fontSize: 15 }} />
              <span className="truncate">{x.label}</span>
              {x.hint && <span className="ml-auto truncate pl-2 text-xs text-muted-foreground">{x.hint}</span>}
            </label>
          </li>
        ))}
      </ul>
      <p className="text-xs text-muted-foreground">{selected.size} selected</p>
    </div>
  );
}

/** Start a review: a title, the questions, the rows; it starts reading at once. */
export function NewReviewDialog({ kind, id, open, onOpenChange, onCreated, initialDocuments, playbook }: {
  kind: WorkspaceKind; id: string; open: boolean; onOpenChange: (o: boolean) => void; onCreated: (review: Review) => void;
  initialDocuments?: string[];
  /** A column-set playbook whose questions start the review. */
  playbook?: { playbook_id: string; title: string; column_count: number } | null;
}) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const [title, setTitle] = useState("");
  const [groupBy, setGroupBy] = useState<"document" | "folder">("document");
  const [presets, setPresets] = useState<Set<string>>(new Set(["parties", "date", "governing_law"]));
  const [customs, setCustoms] = useState<Custom[]>([]);
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (open) {
      setSelected(new Set(initialDocuments ?? []));
      setError(null);
      if (playbook) {
        setPresets(new Set());
        setTitle((t) => t || playbook.title);
      }
    }
  }, [open, initialDocuments, playbook]);
  const columns = columnsFrom(presets, customs);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const review = await createReview({
        title: title.trim(), kind, id, columns, group_by: groupBy, playbook_id: playbook?.playbook_id,
        ...(groupBy === "folder" ? { folders: [...selected] } : { document_ids: [...selected] }), run: true,
      });
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("tab-reviews") });
      toast(selected.size ? "Review started — cells fill in as they are read" : "Review created");
      onOpenChange(false);
      setTitle("");
      onCreated(review);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-2xl overflow-y-auto" data-testid="new-review-dialog">
        <DialogHeader>
          <DialogTitle>New tabular review</DialogTitle>
          <DialogDescription>
            The same questions, answered for every document, each answer with the passage it comes from. It runs as you: it only reads
            documents you can open.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Title" error={error}>
            {(p) => <input {...p} autoFocus value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200}
              placeholder="e.g. Supplier contracts — key terms" className={fieldControl} data-testid="new-review-title" />}
          </Field>
          {playbook && (
            <p className="rounded-md bg-wine-soft px-3 py-2 text-xs text-wine" data-testid="new-review-playbook">
              Starts with the {playbook.column_count} questions of “{playbook.title}”. Add more below if you need them.
            </p>
          )}
          <ColumnPicker presets={presets} setPresets={setPresets} customs={customs} setCustoms={setCustoms} />
          <div>
            <div className="mb-1.5 flex items-center gap-3 text-xs font-medium text-muted-foreground">
              Rows
              <span className="flex rounded-md border border-border p-0.5" role="radiogroup" aria-label="One row per">
                {(["document", "folder"] as const).map((g) => (
                  <button key={g} type="button" role="radio" aria-checked={groupBy === g}
                    onClick={() => { setGroupBy(g); setSelected(new Set()); }}
                    className={cn("rounded px-2 py-0.5", groupBy === g ? "bg-secondary font-medium text-foreground" : "")}>
                    {g === "document" ? "One per document" : "One per folder"}
                  </button>
                ))}
              </span>
            </div>
            <RowPicker kind={kind} id={id} groupBy={groupBy} selected={selected} setSelected={setSelected} open={open} />
          </div>
          <div className="flex items-center justify-end gap-2">
            <span className="mr-auto text-xs text-muted-foreground">{columns.length + (playbook?.column_count ?? 0)} questions × {selected.size} rows</span>
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={busy || !title.trim() || columns.length + (playbook?.column_count ?? 0) === 0} onClick={submit} data-testid="new-review-create">
              {selected.size ? "Create and run" : "Create"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AddColumnsDialog({ reviewId, open, onOpenChange, onDone }: { reviewId: string; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const { toast } = useApp();
  const [presets, setPresets] = useState<Set<string>>(new Set());
  const [customs, setCustoms] = useState<Custom[]>([{ ...EMPTY_CUSTOM }]);
  const columns = columnsFrom(presets, customs);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl" data-testid="add-columns-dialog">
        <DialogHeader>
          <DialogTitle>Add questions</DialogTitle>
          <DialogDescription>New columns are answered for every row straight away.</DialogDescription>
        </DialogHeader>
        <ColumnPicker presets={presets} setPresets={setPresets} customs={customs} setCustoms={setCustoms} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!columns.length} data-testid="add-columns-confirm" onClick={async () => {
            try {
              await addColumns(reviewId, columns);
              onDone();
              onOpenChange(false);
              setPresets(new Set());
              setCustoms([{ ...EMPTY_CUSTOM }]);
            } catch (err) {
              toast(firmError(err));
            }
          }}>Add and run</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function AddRowsDialog({ review, open, onOpenChange, onDone }: { review: Review; open: boolean; onOpenChange: (o: boolean) => void; onDone: () => void }) {
  const { toast } = useApp();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const present = useMemo(() => new Set(review.rows.map((r) => r.document_id ?? r.folder_path ?? "")), [review.rows]);
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="add-rows-dialog">
        <DialogHeader>
          <DialogTitle>Add rows</DialogTitle>
          <DialogDescription>Every question is answered for the new rows.</DialogDescription>
        </DialogHeader>
        <RowPicker kind={review.container_kind} id={review.container_id} groupBy={review.group_by} selected={selected}
          setSelected={setSelected} open={open} exclude={present} />
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!selected.size} data-testid="add-rows-confirm" onClick={async () => {
            try {
              const out = await addRows(review.review_id, review.group_by === "folder" ? { folders: [...selected] } : { document_ids: [...selected] });
              toast(`${out.added} rows added`);
              onDone();
              onOpenChange(false);
              setSelected(new Set());
            } catch (err) {
              toast(firmError(err));
            }
          }}>Add and run</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** The workspace's reviews (side view). */
export function ReviewsView({ kind, id, canEdit, onOpen }: { kind: WorkspaceKind; id: string; canEdit: boolean; onOpen: (reviewId: string, title: string) => void }) {
  const reviews = useReviews(kind, id === "me" ? "me" : id);
  const [creating, setCreating] = useState(false);
  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="workbench-reviews">
      <div className="flex items-center gap-1 border-b border-border px-3 py-2">
        <div className="min-w-0 flex-1 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">Tabular reviews</div>
        {canEdit && (
          <button type="button" className="rounded p-1 text-muted-foreground hover:bg-secondary hover:text-foreground" aria-label="New review"
            title="New review" onClick={() => setCreating(true)} data-testid="reviews-new">
            <Icon name="add" style={{ fontSize: 17 }} />
          </button>
        )}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {reviews.isPending ? (
          <p className="px-3 py-3 text-xs text-muted-foreground">Loading…</p>
        ) : !reviews.data?.length ? (
          <div className="px-3 py-4 text-xs text-muted-foreground">
            Ask the same questions of many documents at once: parties, dates, governing law, your own.
            {canEdit && <Button size="sm" variant="outline" className="mt-3 w-full" onClick={() => setCreating(true)}>New review</Button>}
          </div>
        ) : (
          <ul className="divide-y divide-border">
            {reviews.data.map((r) => (
              <li key={r.review_id}>
                <button type="button" className="w-full px-3 py-2 text-left hover:bg-secondary/70" onClick={() => onOpen(r.review_id, r.title)} data-testid="reviews-item">
                  <div className="flex items-center gap-1.5 text-[13px] font-medium">
                    <Icon name="table_chart" className="text-muted-foreground" style={{ fontSize: 15 }} />
                    <span className="truncate">{r.title}</span>
                  </div>
                  <div className="mt-0.5 text-[11px] text-muted-foreground">
                    {r.row_count} rows × {r.column_count} questions{r.open_cells ? ` · ${r.open_cells} open` : ""} · {formatDate(r.updated_at)}
                  </div>
                </button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <NewReviewDialog kind={kind} id={id} open={creating} onOpenChange={setCreating} onCreated={(r) => onOpen(r.review_id, r.title)} />
    </div>
  );
}
