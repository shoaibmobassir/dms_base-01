import { useMemo, useRef, useState, type UIEvent } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import {
  FORMAT_LABEL,
  deleteColumn,
  deleteRow,
  exportReview,
  overrideCell,
  runReview,
  updateColumn,
  useReview,
  type AnswerFormat,
  type Review,
  type ReviewCell,
  type ReviewColumn,
  type ReviewRow,
} from "@/api/tabular";
import { saveReviewAsPlaybook } from "@/api/playbooks";
import { Field, fieldControl } from "@/components/common/Field";
import { EmptyState, Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";
import { AddColumnsDialog, AddRowsDialog } from "./ReviewDialogs";
import type { OpenRequest } from "./Explorer";

const ROW_H = 72;
const FIRST_W = 260;
const COL_W = 260;
const STATUS_LABEL: Record<string, string> = {
  pending: "Waiting", running: "Reading…", not_found: "Not in the document", failed: "Could not answer", stale: "Question changed",
};

/** A tabular review as a table tab: rows are documents (or folders), columns are questions, cells fill live. */
export function ReviewTable({ reviewId, onOpenSource }: { reviewId: string; onOpenSource: (r: OpenRequest) => void }) {
  const review = useReview(reviewId);
  if (review.isPending) return <div className="p-6 text-sm text-muted-foreground">Loading review…</div>;
  if (review.isError || !review.data) {
    return (
      <div className="flex h-full items-center justify-center p-6">
        <EmptyState icon="lock" title="Review not found" description="It was archived, or you are not one of its workspace's people." />
      </div>
    );
  }
  return <Table review={review.data} onOpenSource={onOpenSource} />;
}

function Table({ review, onOpenSource }: { review: Review; onOpenSource: (r: OpenRequest) => void }) {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const canEdit = review.my_level !== "read" && !review.archived_at;
  const cells = useMemo(() => new Map(review.cells.map((c) => [`${c.row_id}|${c.column_id}`, c])), [review.cells]);
  const [scrollTop, setScrollTop] = useState(0);
  const [height, setHeight] = useState(600);
  const box = useRef<HTMLDivElement | null>(null);
  const [selected, setSelected] = useState<{ row: ReviewRow; col: ReviewColumn } | null>(null);
  const [editingCol, setEditingCol] = useState<ReviewColumn | null>(null);
  const [adding, setAdding] = useState<"columns" | "rows" | null>(null);
  const [filter, setFilter] = useState<"all" | "open" | "not_found">("all");

  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(review.review_id) || q.queryKey.includes("tab-reviews") });
  const act = async (fn: () => Promise<unknown>, done?: string) => {
    try {
      await fn();
      await refresh();
      if (done) toast(done);
    } catch (err) {
      toast(firmError(err));
    }
  };

  const rows = review.rows.filter((r) => {
    if (filter === "all") return true;
    const mine = review.columns.map((c) => cells.get(`${r.row_id}|${c.column_id}`));
    if (filter === "open") return mine.some((c) => c && ["pending", "running", "stale", "failed"].includes(c.status));
    return mine.some((c) => c?.status === "not_found");
  });
  const first = Math.max(0, Math.floor(scrollTop / ROW_H) - 5);
  const last = Math.min(rows.length, Math.ceil((scrollTop + height) / ROW_H) + 5);
  const total = review.cells.length;
  const done = (review.counts.done ?? 0) + (review.counts.not_found ?? 0) + (review.counts.failed ?? 0);
  const open = (review.counts.pending ?? 0) + (review.counts.running ?? 0) + (review.counts.stale ?? 0);
  const onScroll = (e: UIEvent<HTMLDivElement>) => {
    setScrollTop(e.currentTarget.scrollTop);
    setHeight(e.currentTarget.clientHeight);
  };

  return (
    <div className="flex h-full min-h-0 flex-col" data-testid="review-table">
      <div className="flex flex-wrap items-center gap-2 border-b border-border bg-card px-3 py-2">
        <Icon name="table_chart" className="text-wine" style={{ fontSize: 20 }} />
        <h2 className="min-w-0 truncate font-display text-lg text-ink">{review.title}</h2>
        <span className="text-xs text-muted-foreground">
          {review.rows.length} {review.group_by === "folder" ? "folders" : "documents"} × {review.columns.length} questions
        </span>
        {open > 0 ? (
          <span className="flex items-center gap-1.5 text-xs text-muted-foreground" data-testid="review-progress">
            <span className="inline-block h-1.5 w-24 overflow-hidden rounded-full bg-secondary">
              <span className="block h-full bg-wine transition-all" style={{ width: `${total ? (done / total) * 100 : 0}%` }} />
            </span>
            {done} of {total}
          </span>
        ) : (
          <span className="text-xs text-muted-foreground" data-testid="review-progress">All answered</span>
        )}
        <div className="flex-1" />
        <select value={filter} onChange={(e) => setFilter(e.target.value as typeof filter)} aria-label="Show rows"
          className="h-8 rounded-md border border-border bg-card px-2 text-xs">
          <option value="all">All rows</option>
          <option value="open">Rows still open</option>
          <option value="not_found">Rows with gaps</option>
        </select>
        {canEdit && (
          <>
            <Button size="sm" variant="outline" onClick={() => setAdding("rows")} data-testid="review-add-rows">
              <Icon name="playlist_add" style={{ fontSize: 16 }} /> Rows
            </Button>
            <Button size="sm" variant="outline" onClick={() => setAdding("columns")} data-testid="review-add-columns">
              <Icon name="add_column_right" style={{ fontSize: 16 }} /> Question
            </Button>
            <Button size="sm" onClick={() => act(() => runReview(review.review_id, { scope: "open" }), "Running the open cells")}
              disabled={open === 0 && !review.counts.failed} data-testid="review-run">
              <Icon name="play_arrow" style={{ fontSize: 16 }} /> Run
            </Button>
          </>
        )}
        <Button size="sm" variant="ghost" onClick={() => act(() => exportReview(review.review_id, review.title))} data-testid="review-export">
          <Icon name="download" style={{ fontSize: 16 }} /> Excel
        </Button>
        <Button size="sm" variant="ghost" title="Keep these questions as a playbook to start the next review with"
          onClick={() => act(() => saveReviewAsPlaybook(review.review_id), "Questions saved to your playbooks")} data-testid="review-save-playbook">
          <Icon name="bookmark_add" style={{ fontSize: 16 }} />
        </Button>
      </div>

      {review.rows.length === 0 ? (
        <div className="flex flex-1 items-center justify-center p-6">
          <EmptyState icon="playlist_add" title="No rows yet" description="Add the documents (or folders) to review."
            action={canEdit ? <Button onClick={() => setAdding("rows")}>Add rows</Button> : undefined} />
        </div>
      ) : (
        <div ref={box} className="relative min-h-0 flex-1 overflow-auto" onScroll={onScroll} role="grid" tabIndex={0}
          aria-label={`${review.title}: answers by document and question`}
          // Focus and scrolling into view keep clear of the sticky name column and header row.
          style={{ scrollPaddingLeft: FIRST_W, scrollPaddingTop: ROW_H }}
          aria-rowcount={rows.length + 1} aria-colcount={review.columns.length + 1}>
          <div style={{ width: FIRST_W + review.columns.length * COL_W, height: (rows.length + 1) * ROW_H }} className="relative">
            {/* header */}
            <div className="sticky top-0 z-20 flex bg-paper" role="row" style={{ height: ROW_H }}>
              <div className="sticky left-0 z-30 flex items-end border-b border-r border-border bg-paper px-3 pb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground" style={{ width: FIRST_W }} role="columnheader">
                {review.group_by === "folder" ? "Folder" : "Document"}
              </div>
              {review.columns.map((c) => (
                <ColumnHeader key={c.column_id} col={c} canEdit={canEdit}
                  onEdit={() => setEditingCol(c)}
                  onRun={() => act(() => runReview(review.review_id, { scope: "column", column_id: c.column_id }), `Running “${c.label}”`)}
                  onDelete={() => act(() => deleteColumn(review.review_id, c.column_id), "Question removed")} />
              ))}
            </div>
            {/* body (only the rows in view) */}
            {rows.slice(first, last).map((r, i) => (
              <div key={r.row_id} className="absolute left-0 flex" role="row" style={{ top: (first + i + 1) * ROW_H, height: ROW_H }} data-testid="review-row">
                <RowHeader row={r} canEdit={canEdit}
                  onOpen={() => r.document_id && onOpenSource({ documentId: r.document_id, title: r.title ?? "", toSide: true })}
                  onRun={() => act(() => runReview(review.review_id, { scope: "row", row_id: r.row_id }))}
                  onRemove={() => act(() => deleteRow(review.review_id, r.row_id), "Row removed")} />
                {review.columns.map((c) => (
                  <CellView key={c.column_id} cell={cells.get(`${r.row_id}|${c.column_id}`)} rowRestricted={r.restricted}
                    format={c.answer_format} onSelect={() => setSelected({ row: r, col: c })} />
                ))}
              </div>
            ))}
          </div>
        </div>
      )}

      {selected && (
        <CellDialog review={review} row={selected.row} col={selected.col} cell={cells.get(`${selected.row.row_id}|${selected.col.column_id}`)}
          canEdit={canEdit} onClose={() => setSelected(null)} onOpenSource={onOpenSource} act={act} />
      )}
      {editingCol && <ColumnDialog reviewId={review.review_id} col={editingCol} onClose={() => setEditingCol(null)} act={act} />}
      <AddColumnsDialog reviewId={review.review_id} open={adding === "columns"} onOpenChange={(o) => !o && setAdding(null)} onDone={refresh} />
      <AddRowsDialog review={review} open={adding === "rows"} onOpenChange={(o) => !o && setAdding(null)} onDone={refresh} />
    </div>
  );
}

function ColumnHeader({ col, canEdit, onEdit, onRun, onDelete }: { col: ReviewColumn; canEdit: boolean; onEdit: () => void; onRun: () => void; onDelete: () => void }) {
  return (
    <div className="group flex shrink-0 flex-col justify-end border-b border-r border-border px-3 pb-2" style={{ width: COL_W }} role="columnheader" title={col.question} data-testid="review-column">
      <div className="flex items-center gap-1">
        <span className="min-w-0 flex-1 truncate text-[13px] font-semibold">{col.label}</span>
        {canEdit && (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <button type="button" aria-label={`${col.label} options`} className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-secondary group-hover:opacity-100 data-[state=open]:opacity-100">
                <Icon name="more_horiz" style={{ fontSize: 16 }} />
              </button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={onEdit}><Icon name="edit" style={{ fontSize: 16 }} /> Edit question</DropdownMenuItem>
              <DropdownMenuItem onSelect={onRun}><Icon name="refresh" style={{ fontSize: 16 }} /> Run this column again</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={onDelete} className="text-destructive"><Icon name="delete" style={{ fontSize: 16 }} /> Remove column</DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        )}
      </div>
      <span className="truncate text-[11px] text-muted-foreground">{FORMAT_LABEL[col.answer_format]} · {col.question}</span>
    </div>
  );
}

function RowHeader({ row, canEdit, onOpen, onRun, onRemove }: { row: ReviewRow; canEdit: boolean; onOpen: () => void; onRun: () => void; onRemove: () => void }) {
  return (
    <div className="group sticky left-0 z-10 flex shrink-0 items-center gap-2 border-b border-r border-border bg-card px-3" style={{ width: FIRST_W }} role="rowheader">
      <Icon name={row.restricted ? "lock" : row.kind === "folder" ? "folder" : "description"} className="text-muted-foreground" style={{ fontSize: 16 }} />
      {row.restricted ? (
        <span className="truncate text-[13px] italic text-muted-foreground">Restricted document</span>
      ) : (
        <button type="button" className="min-w-0 flex-1 truncate text-left text-[13px] hover:text-wine hover:underline" onClick={onOpen}
          disabled={row.kind === "folder"} title={row.title ?? ""}>
          {row.title}
        </button>
      )}
      {row.running && <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-wine" aria-label="Reading" />}
      {canEdit && !row.restricted && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button type="button" aria-label="Row options" className="rounded p-0.5 text-muted-foreground opacity-0 hover:bg-secondary group-hover:opacity-100 data-[state=open]:opacity-100">
              <Icon name="more_horiz" style={{ fontSize: 16 }} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            <DropdownMenuItem onSelect={onRun}><Icon name="refresh" style={{ fontSize: 16 }} /> Run this row again</DropdownMenuItem>
            <DropdownMenuItem onSelect={onRemove} className="text-destructive"><Icon name="delete" style={{ fontSize: 16 }} /> Remove row</DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
    </div>
  );
}

function CellView({ cell, rowRestricted, format, onSelect }: { cell?: ReviewCell; rowRestricted: boolean; format: AnswerFormat; onSelect: () => void }) {
  const restricted = rowRestricted || cell?.restricted;
  const status = cell?.status ?? "pending";
  const answered = cell && !restricted && (status === "done" || cell.edited);
  return (
    <button
      type="button"
      role="gridcell"
      onClick={onSelect}
      disabled={restricted}
      className={cn(
        "flex shrink-0 flex-col items-start gap-0.5 overflow-hidden border-b border-r border-border px-3 py-2 text-left text-[13px] hover:bg-secondary/60",
        status === "stale" && "bg-warning-soft/40",
        status === "failed" && "text-destructive",
      )}
      style={{ width: COL_W, height: ROW_H }}
      data-testid="review-cell"
      data-status={restricted ? "restricted" : status}
    >
      {restricted ? (
        <span className="flex items-center gap-1 text-xs italic text-muted-foreground"><Icon name="lock" style={{ fontSize: 13 }} /> Restricted</span>
      ) : answered ? (
        <>
          <span className={cn("line-clamp-2 w-full", format === "yes_no" && "font-medium", status === "stale" && "text-muted-foreground line-through decoration-muted-foreground/40")}>
            {cell.answer}
          </span>
          <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
            {cell.edited ? <><Icon name="person_edit" style={{ fontSize: 12 }} /> edited</>
              : cell.citations?.[0]?.verified ? <><Icon name="format_quote" style={{ fontSize: 12 }} /> {cell.citations[0].page ? `p. ${cell.citations[0].page}` : "quoted"}</>
              : cell.citations?.[0] ? <><Icon name="help" style={{ fontSize: 12 }} /> quote not found</> : null}
          </span>
        </>
      ) : (
        <span className={cn("text-xs", status === "running" ? "animate-pulse text-wine" : "text-muted-foreground")}>{STATUS_LABEL[status] ?? status}</span>
      )}
    </button>
  );
}

function CellDialog({
  review,
  row,
  col,
  cell,
  canEdit,
  onClose,
  onOpenSource,
  act,
}: {
  review: Review
  row: ReviewRow
  col: ReviewColumn
  cell?: ReviewCell
  canEdit: boolean
  onClose: () => void
  onOpenSource: (r: OpenRequest) => void
  act: (fn: () => Promise<unknown>, done?: string) => Promise<void>
}) {
  const [editing, setEditing] = useState(false);
  const [value, setValue] = useState(cell?.answer ?? "");
  const cit = cell?.citations?.[0];
  const openSource = () => {
    if (!cit?.document_id) return;
    const p = new URLSearchParams();
    if (cit.page) p.set("page", String(cit.page));
    if (cit.chunk_id) p.set("chunk", cit.chunk_id);
    onOpenSource({ documentId: cit.document_id, title: row.title ?? "", toSide: true, params: p.toString() });
    onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-xl" data-testid="review-cell-dialog">
        <DialogHeader>
          <DialogTitle>{col.label}</DialogTitle>
          <DialogDescription>{row.title} · {col.question}</DialogDescription>
        </DialogHeader>
        {editing ? (
          <div className="space-y-2">
            <textarea value={value} onChange={(e) => setValue(e.target.value)} rows={4} maxLength={4000} className={fieldControl} data-testid="review-cell-edit" />
            <div className="flex justify-end gap-2">
              <Button variant="outline" size="sm" onClick={() => setEditing(false)}>Cancel</Button>
              <Button size="sm" disabled={!value.trim()} onClick={() => act(() => overrideCell(review.review_id, row.row_id, col.column_id, value), "Answer saved").then(onClose)} data-testid="review-cell-save">
                Save my answer
              </Button>
            </div>
          </div>
        ) : (
          <div className="space-y-3 text-sm">
            <p className="whitespace-pre-wrap text-base" data-testid="review-cell-answer">
              {cell?.answer || (cell ? STATUS_LABEL[cell.status] ?? cell.status : "Not run yet")}
            </p>
            {cell?.error && <p className="text-xs text-destructive">{cell.error}</p>}
            {cell?.edited && (
              <p className="text-xs text-muted-foreground">
                A lawyer's answer.{cell.model_answer ? ` The model had answered: “${cell.model_answer}”.` : ""}
              </p>
            )}
            {cit && (
              <figure className="rounded-md border-l-2 border-highlight bg-secondary/50 px-3 py-2">
                <blockquote className="text-sm italic">“{cit.quote}”</blockquote>
                <figcaption className="mt-1 text-xs text-muted-foreground">
                  {cit.verified ? "Found in the document" : "Not found word for word in the document — check it"}
                  {cit.page ? ` · page ${cit.page}` : ""}
                </figcaption>
              </figure>
            )}
            <div className="flex flex-wrap gap-2">
              {cit?.document_id && <Button size="sm" variant="outline" onClick={openSource} data-testid="review-open-source"><Icon name="vertical_split" style={{ fontSize: 15 }} /> Open source beside the table</Button>}
              {canEdit && <Button size="sm" variant="outline" onClick={() => { setValue(cell?.answer ?? ""); setEditing(true); }}><Icon name="edit" style={{ fontSize: 15 }} /> Write my own answer</Button>}
              {canEdit && cell?.edited && <Button size="sm" variant="ghost" onClick={() => act(() => overrideCell(review.review_id, row.row_id, col.column_id, null), "Model answer restored").then(onClose)}>Use the model's answer</Button>}
              {canEdit && !cell?.edited && <Button size="sm" variant="ghost" onClick={() => act(() => runReview(review.review_id, { scope: "cell", row_id: row.row_id, column_id: col.column_id })).then(onClose)}><Icon name="refresh" style={{ fontSize: 15 }} /> Run again</Button>}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}

function ColumnDialog({ reviewId, col, onClose, act }: { reviewId: string; col: ReviewColumn; onClose: () => void; act: (fn: () => Promise<unknown>, done?: string) => Promise<void> }) {
  const [label, setLabel] = useState(col.label);
  const [question, setQuestion] = useState(col.question);
  const [format, setFormat] = useState<AnswerFormat>(col.answer_format);
  const [choices, setChoices] = useState(col.choices.join(", "));
  const changesMeaning = question !== col.question || format !== col.answer_format || choices !== col.choices.join(", ");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="review-column-dialog">
        <DialogHeader>
          <DialogTitle>Edit question</DialogTitle>
          <DialogDescription>Renaming keeps the answers. Changing the question or its format marks the column's answers as out of date until you run it again.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <Field label="Column name">{(p) => <input {...p} value={label} onChange={(e) => setLabel(e.target.value)} maxLength={120} className={fieldControl} />}</Field>
          <Field label="Question">{(p) => <textarea {...p} value={question} onChange={(e) => setQuestion(e.target.value)} rows={3} maxLength={2000} className={fieldControl} />}</Field>
          <Field label="Answer as">
            {(p) => (
              <select {...p} value={format} onChange={(e) => setFormat(e.target.value as AnswerFormat)} className={fieldControl}>
                {Object.entries(FORMAT_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            )}
          </Field>
          {format === "choice" && (
            <Field label="Choices" hint="Separate with commas">{(p) => <input {...p} value={choices} onChange={(e) => setChoices(e.target.value)} className={fieldControl} />}</Field>
          )}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button onClick={() => act(() => updateColumn(reviewId, col.column_id, {
              label, question, answer_format: format, choices: choices.split(",").map((c) => c.trim()).filter(Boolean),
            }), changesMeaning ? "Saved — run the column again to update its answers" : "Saved").then(onClose)}>Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
