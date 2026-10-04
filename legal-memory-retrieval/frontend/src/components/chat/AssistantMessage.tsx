import { useState } from "react";
import type { AskInputItem, Attachment, ChatEvent, Citation, EditProposal } from "@/api/types";
import type { PanelSource } from "@/components/chat/CitationDocumentPanel";
import { ReviewTableCard, type ReviewTableEvent } from "@/components/chat/ReviewTableCard";
import { AskInputsCard, CommentsAddedCard, type CommentsAddedEvent, type EditGroup, EditProposalsCard, FileCard, StepTimeline } from "@/components/chat/MessageParts";
import { Markdown } from "@/components/chat/Markdown";
import { citationChipClass } from "@/components/common/citation";
import { cn } from "@/lib/utils";
import { ArrowUpRight, Check, Copy, FileText, Link2, RotateCcw } from "lucide-react";
import { toast } from "sonner";
import type { UiMessage } from "@/components/chat/chatTypes";
import { citationQuotes, quoted } from "@/components/chat/citationText";

export function AssistantMessage({
  message: m,
  sessionId,
  isLast,
  onRetry,
  onOpenCitation,
  onOpenSource,
  onAnswer,
  onUpload,
}: {
  message: UiMessage;
  sessionId?: string;
  isLast: boolean;
  onRetry?: () => void;
  onOpenCitation: (c?: Citation) => void;
  onOpenSource: (source: Omit<PanelSource, "nonce">) => void;
  onAnswer: (text: string, files: Attachment[]) => void;
  onUpload: (file: File) => Promise<Attachment | null>;
}) {
  const [copied, setCopied] = useState(false);
  const [showSources, setShowSources] = useState(false);
  const [madeFiles, setMadeFiles] = useState<{ document_id: string; filename: string }[]>([]);
  const citations = (m.citations ?? []) as Citation[];
  const events = (m.events ?? []) as ChatEvent[];
  const byRef = (n: number) => citations.find((c) => Number(c.ref) === n);
  const askItems = events.filter((e) => e.type === "ask_inputs").flatMap((e) => (e.items ?? []) as AskInputItem[]);
  const editGroups = events.filter((e) => e.type === "edit_proposals") as unknown as EditGroup[];
  const commentGroups = events.filter((e) => e.type === "comments_added") as unknown as CommentsAddedEvent[];
  const reviewTables = events.filter((e) => e.type === "review_table") as unknown as ReviewTableEvent[];
  const files = [
    ...events
      .filter((e) => e.type === "doc_created" && typeof e.document_id === "string")
      .map((e) => ({ document_id: String(e.document_id), filename: String(e.filename ?? "Document") })),
    ...madeFiles,
  ];
  const showEdit = (group: EditGroup, edit: EditProposal) =>
    onOpenSource({
      documentId: group.document_id,
      title: group.filename,
      label: "Suggested edit",
      quotes: [{ page: edit.page, quote: edit.original }],
    });

  const openCitation = (c?: Citation) => onOpenCitation(c);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(m.content);
      setCopied(true);
      toast.success("Answer copied");
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // clipboard blocked
    }
  };

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(window.location.href);
      toast.success("Link to this conversation copied");
    } catch {
      // clipboard blocked
    }
  };
  const citedDocs = new Set(citations.map((c) => String(c.document_id ?? "")).filter(Boolean)).size;

  const streaming = m.status === "streaming";
  // One chip per cited document; opening a chip opens its first cited passage.
  const docChips: { id: string; title: string; first: Citation; n: number }[] = [];
  for (const c of citations) {
    const id = String(c.document_id ?? "");
    if (!id) continue;
    const chip = docChips.find((d) => d.id === id);
    if (chip) chip.n += 1;
    else docChips.push({ id, title: String(c.title ?? id), first: c, n: 1 });
  }
  const actionBtn =
    "inline-flex h-8 w-8 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground";

  return (
    <div className="group/message w-full" data-testid="assistant-message">
      <div className="flex gap-3">
        <span
          className="mt-0.5 hidden h-7 w-7 shrink-0 items-center justify-center rounded-full bg-wine font-display text-sm leading-none text-primary-foreground sm:flex"
          aria-hidden="true"
        >
          P
        </span>
        <div className="min-w-0 flex-1">
          <StepTimeline events={events} streaming={streaming} />

          {m.content ? (
            <div className="text-[15.5px] leading-[1.75] text-ink">
              <Markdown
                text={m.content}
                paragraphClassName="my-2 text-[15.5px] leading-[1.75] text-ink"
                renderCitation={(n) => {
                  const c = byRef(n);
                  return <CitationBadge num={n} citation={c} onOpen={() => openCitation(c)} />;
                }}
              />
              {streaming && <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-wine/70" aria-hidden="true" />}
            </div>
          ) : streaming ? (
            <p className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
              <span className="h-2 w-2 animate-pulse rounded-full bg-wine" />
              Working on it…
            </p>
          ) : null}

          {askItems.length > 0 && (
            <AskInputsCard items={askItems} answered={!isLast || streaming} onSubmit={onAnswer} onUpload={onUpload} />
          )}

          {reviewTables.map((table, ti) => (
            <ReviewTableCard key={`${m.id ?? "live"}-review-${ti}`} table={table} onOpen={onOpenSource} />
          ))}

          {commentGroups.map((group, gi) => (
            <CommentsAddedCard key={`${m.id ?? "live"}-comments-${gi}`} event={group} />
          ))}

          {editGroups.map((group, gi) => (
            <EditProposalsCard
              key={`${m.id ?? "live"}-${gi}`}
              group={group}
              sessionId={sessionId}
              messageId={streaming ? undefined : m.id}
              onView={(edit) => showEdit(group, edit)}
              onFileReady={(f) => setMadeFiles((list) => [...list, f])}
            />
          ))}

          {files.map((f) => (
            <FileCard
              key={f.document_id}
              documentId={f.document_id}
              filename={f.filename}
              onOpen={() => onOpenSource({ documentId: f.document_id, title: f.filename, label: "Generated file", quotes: [], generated: true })}
            />
          ))}

          {m.status === "stopped" && (
            <p className="mt-3 text-xs text-muted-foreground" data-testid="chat-stopped">
              Stopped. The partial answer above has been saved.
            </p>
          )}

          {m.status === "error" && (
            <div className="mt-3 flex items-center justify-between gap-4 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs" data-testid="chat-error">
              <span className="text-destructive">{m.error ?? "The assistant could not complete the request."}</span>
              {onRetry && (
                <button type="button" onClick={onRetry} className="shrink-0 cursor-pointer font-semibold text-foreground hover:underline">
                  Retry
                </button>
              )}
            </div>
          )}

          {citations.length > 0 && (
            <div className="mt-4" data-testid="chat-sources">
              <div className="flex flex-wrap items-center gap-1.5">
                <span className="mr-1 text-xs font-medium text-muted-foreground" data-testid="message-citation-count">
                  {citedDocs} {citedDocs === 1 ? "source" : "sources"}
                </span>
                {docChips.map((d) => (
                  <button
                    key={d.id}
                    type="button"
                    onClick={() => openCitation(d.first)}
                    title={d.title}
                    data-testid="source-chip"
                    className="inline-flex max-w-[220px] items-center gap-1.5 rounded-full border border-border bg-card px-2.5 py-1 text-xs text-foreground transition-colors hover:border-wine/40 hover:bg-wine-soft"
                  >
                    <FileText className="h-3 w-3 shrink-0 text-muted-foreground" />
                    <span className="truncate">{d.title.replace(/\.(docx?|pdf|txt)$/i, "")}</span>
                    {d.n > 1 && <span className="shrink-0 text-muted-foreground">{d.n}</span>}
                  </button>
                ))}
                <button
                  type="button"
                  onClick={() => setShowSources((v) => !v)}
                  aria-expanded={showSources}
                  data-testid="sources-toggle"
                  className="ml-1 text-xs font-medium text-wine hover:underline"
                >
                  {showSources ? "Hide passages" : "Show passages"}
                </button>
              </div>
              {showSources && (
                <div className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {citations.map((c, i) => (
                    <button
                      key={i}
                      type="button"
                      onClick={() => openCitation(c)}
                      className="group flex cursor-pointer flex-col rounded-lg border border-border p-2.5 text-left text-xs transition-colors hover:bg-secondary/50"
                    >
                      <div className="flex items-center justify-between font-medium text-ink group-hover:text-primary">
                        <span className="truncate">
                          <span className="mr-1 font-mono-id font-semibold text-wine">[{String(c.ref ?? i + 1)}]</span>
                          {String(c.title ?? c.document_id ?? "Document")}
                        </span>
                        <ArrowUpRight className="h-3 w-3 shrink-0 text-muted-foreground group-hover:text-primary" />
                      </div>
                      {citationQuotes(c).map((q, qi) => (
                        <p key={qi} className="mt-1 line-clamp-3 text-xs italic text-muted-foreground">
                          {quoted(q)}
                        </p>
                      ))}
                      <div className="mt-1 flex items-center gap-2 text-xs text-muted-foreground">
                        {c.page != null && <span className="font-mono">p. {String(c.page)}</span>}
                        {Array.isArray(c.quotes) && c.quotes.length > 1 && <span>{c.quotes.length} quotes</span>}
                        {c.support === "partial" && (
                          <span className="font-semibold text-warning-ink" data-testid="citation-partial">
                            Partly supported
                          </span>
                        )}
                        {c.verified === false && (
                          <span className="font-semibold text-warning-ink" data-testid="citation-unverified">
                            Not confirmed
                          </span>
                        )}
                      </div>
                    </button>
                  ))}
                </div>
              )}
            </div>
          )}

          {!streaming && m.content && (
            <div
              className={cn(
                "mt-2 -ml-2 flex items-center gap-0.5 transition-opacity",
                isLast ? "opacity-100" : "opacity-0 focus-within:opacity-100 group-hover/message:opacity-100 [@media(hover:none)]:opacity-100",
              )}
              data-testid="message-actions"
            >
              <button type="button" onClick={() => void copy()} title="Copy answer" aria-label="Copy answer" className={actionBtn} data-testid="message-copy">
                {copied ? <Check className="h-4 w-4 text-success-ink" /> : <Copy className="h-4 w-4" />}
              </button>
              {onRetry && (
                <button type="button" onClick={onRetry} title="Regenerate answer" aria-label="Regenerate answer" className={actionBtn} data-testid="message-regenerate">
                  <RotateCcw className="h-4 w-4" />
                </button>
              )}
              <button type="button" onClick={() => void copyLink()} title="Copy link to this conversation" aria-label="Copy link to this conversation" className={actionBtn}>
                <Link2 className="h-4 w-4" />
              </button>
              {m.created_at && (
                <time className="ml-2 text-xs text-muted-foreground" dateTime={m.created_at}>
                  {new Date(m.created_at).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })}
                </time>
              )}
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

// ── citation badge with hover preview ──────────────────────────────────────

function CitationBadge({ num, citation, onOpen }: { num: number; citation?: Citation; onOpen: () => void }) {
  const [hovered, setHovered] = useState(false);

  return (
    <span
      className="relative inline-block align-baseline"
      onMouseEnter={() => setHovered(true)}
      onMouseLeave={() => setHovered(false)}
    >
      <button
        type="button"
        onClick={onOpen}
        data-testid={`chat-citation-${num}`}
        title={
          citation?.verified === false
            ? "Quote not confirmed in the document text"
            : citation?.support === "partial"
              ? "The cited text supports only part of this statement"
              : undefined
        }
        className={citationChipClass({
          partial: citation?.verified === false || citation?.support === "partial",
          className: cn("cursor-pointer", !citation && "cursor-default opacity-60"),
        })}
      >
        <span>[{num}]</span>
        {citation?.verified === false && <span aria-hidden>?</span>}
      </button>

      {/* Hover preview */}
      {hovered && citation && (
        <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-2 w-64 p-3 rounded-lg shadow-xl border border-border bg-popover text-popover-foreground text-left text-xs z-50 animate-in fade-in-0 zoom-in-95 pointer-events-auto">
          <span className="mb-1 block truncate font-semibold text-ink">
            {String(citation.title ?? citation.document_id ?? `Source [${num}]`)}
          </span>
          {typeof citation.quote === "string" && citation.quote && (
            <span className="mb-2 block rounded bg-secondary/50 p-1.5 text-xs italic text-muted-foreground line-clamp-3">
              {quoted(citation.quote)}
            </span>
          )}
          <button
            type="button"
            onClick={onOpen}
            className="w-full text-center py-1 rounded bg-primary text-primary-foreground font-medium text-xs hover:bg-primary/90 transition-colors flex items-center justify-center gap-1 cursor-pointer"
          >
            <span>View in document</span>
            <ArrowUpRight className="w-3 h-3" />
          </button>
        </span>
      )}
    </span>
  );
}
