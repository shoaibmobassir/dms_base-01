import { useState } from "react";
import type { AskInputItem, Attachment, ChatEvent, Citation, EditProposal } from "@/api/types";
import type { PanelSource } from "@/components/chat/CitationDocumentPanel";
import { ReviewTableCard, type ReviewTableEvent } from "@/components/chat/ReviewTableCard";
import { AskInputsCard, type EditGroup, EditProposalsCard, FileCard, StepTimeline } from "@/components/chat/MessageParts";
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
  const [madeFiles, setMadeFiles] = useState<{ document_id: string; filename: string }[]>([]);
  const citations = (m.citations ?? []) as Citation[];
  const events = (m.events ?? []) as ChatEvent[];
  const byRef = (n: number) => citations.find((c) => Number(c.ref) === n);
  const askItems = events.filter((e) => e.type === "ask_inputs").flatMap((e) => (e.items ?? []) as AskInputItem[]);
  const editGroups = events.filter((e) => e.type === "edit_proposals") as unknown as EditGroup[];
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

  return (
    <div className="w-full" data-testid="assistant-message">
      <div className="min-w-0 rounded-xl border border-border bg-card p-5 shadow-2xs">
        <div className="mb-2 flex items-center justify-between gap-2">
          <span className="font-mono text-xs text-muted-foreground" data-testid="message-citation-count" title={m.created_at ? new Date(m.created_at).toLocaleString() : undefined}>
            {citations.length > 0 &&
              `${citations.length} ${citations.length === 1 ? "citation" : "citations"} · ${citedDocs} ${citedDocs === 1 ? "document" : "documents"}`}
          </span>
          <div className="flex shrink-0 items-center gap-0.5">
            <button
              type="button"
              onClick={() => void copy()}
              title="Copy answer"
              aria-label="Copy answer"
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              {copied ? <Check className="h-3.5 w-3.5 text-success-ink" /> : <Copy className="h-3.5 w-3.5" />}
            </button>
            {onRetry && (
              <button
                type="button"
                onClick={onRetry}
                title="Regenerate answer"
                aria-label="Regenerate answer"
                className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
              >
                <RotateCcw className="h-3.5 w-3.5" />
              </button>
            )}
            <button
              type="button"
              onClick={() => void copyLink()}
              title="Copy link to this conversation"
              aria-label="Copy link to this conversation"
              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
            >
              <Link2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </div>

        <StepTimeline events={events} streaming={m.status === "streaming"} />

        {/* Formatted Legal Reasoning Content */}
        {m.content ? (
          <div className="text-[14.5px] leading-relaxed text-ink">
            <Markdown
              text={m.content}
              renderCitation={(n) => {
                const c = byRef(n);
                return (
                  <CitationBadge
                    num={n}
                    citation={c}
                    onOpen={() => openCitation(c)}
                  />
                );
              }}
            />
          </div>
        ) : m.status === "streaming" ? (
          <p className="flex items-center gap-2 text-xs text-muted-foreground" role="status">
            <span className="h-2 w-2 animate-pulse rounded-full bg-wine" />
            Reviewing relevant matter documents and statutory precedents…
          </p>
        ) : null}

        {askItems.length > 0 && (
          <AskInputsCard items={askItems} answered={!isLast || m.status === "streaming"} onSubmit={onAnswer} onUpload={onUpload} />
        )}

        {reviewTables.map((table, ti) => (
          <ReviewTableCard key={`${m.id ?? "live"}-review-${ti}`} table={table} onOpen={onOpenSource} />
        ))}

        {editGroups.map((group, gi) => (
          <EditProposalsCard
            key={`${m.id ?? "live"}-${gi}`}
            group={group}
            sessionId={sessionId}
            messageId={m.status === "streaming" ? undefined : m.id}
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
            Stopped — the partial answer above has been saved.
          </p>
        )}

        {/* Error handling */}
        {m.status === "error" && (
          <div className="mt-3 flex items-center justify-between gap-4 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-xs" data-testid="chat-error">
            <span className="text-destructive">{m.error ?? "The assistant could not complete the legal query."}</span>
            {onRetry && (
              <button type="button" onClick={onRetry} className="shrink-0 font-semibold text-foreground hover:underline cursor-pointer">
                Retry
              </button>
            )}
          </div>
        )}

        {/* Sources Grid */}
        {citations.length > 0 && (
          <div className="mt-4 pt-3 border-t border-border" data-testid="chat-sources">
            <div className="text-xs font-mono uppercase tracking-wider font-semibold text-muted-foreground mb-2 flex items-center gap-1.5">
              <FileText className="w-3 h-3 text-muted-foreground" />
              <span>Sources ({citations.length})</span>
            </div>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {citations.map((c, i) => (
                <button
                  key={i}
                  type="button"
                  onClick={() => openCitation(c)}
                  className="flex flex-col text-left p-2.5 rounded-lg border border-border hover:bg-secondary/50 transition-colors text-xs group cursor-pointer"
                >
                  <div className="flex items-center justify-between font-medium text-ink group-hover:text-primary">
                    <span className="truncate">
                      <span className="mr-1 font-mono-id text-wine font-semibold">[{String(c.ref ?? i + 1)}]</span>
                      {String(c.title ?? c.document_id ?? "Document")}
                    </span>
                    <ArrowUpRight className="w-3 h-3 text-muted-foreground group-hover:text-primary shrink-0" />
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
          </div>
        )}

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
