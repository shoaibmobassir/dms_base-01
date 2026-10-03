import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { WorkMode } from "@/api/chat";
import type { Attachment } from "@/api/types";
import { Icon } from "@/components/common/primitives";
import { cn } from "@/lib/utils";
import { Check, FileText, Paperclip, Search, ShieldCheck, Sparkles, X } from "lucide-react";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

// What each work mode changes about the answer (see app/chat/system_prompt.py).
export const MODES: { id: WorkMode; label: string; description: string }[] = [
  { id: "cite", label: "Cite", description: "Every statement quotes the passage it relies on." },
  { id: "reason", label: "Reason", description: "Explains which records it will use before answering." },
  { id: "research", label: "Research memo", description: "Legal position, authorities and analysis under headings." },
  { id: "review", label: "Risk review", description: "Table of issues in the documents, with suggested changes." },
];

export function Composer({
  streaming,
  disabled,
  mode,
  onMode,
  uploading,
  attachments,
  draft,
  onRemoveAttachment,
  onOpenAttachment,
  onUpload,
  onPickDocuments,
  onSend,
  onStop,
}: {
  streaming: boolean;
  disabled: boolean;
  mode: WorkMode;
  onMode: (mode: WorkMode) => void;
  uploading: boolean;
  attachments: Attachment[];
  /** Text placed in the box by a starter card; `nonce` changes on every pick. */
  draft?: { text: string; nonce: number };
  onRemoveAttachment: (documentId: string) => void;
  onOpenAttachment: (attachment: Attachment) => void;
  onUpload: (file: File) => void;
  onPickDocuments: () => void;
  onSend: (text: string) => void;
  onStop: () => void;
}) {
  const [text, setText] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);
  const fileRef = useRef<HTMLInputElement>(null);
  const current = MODES.find((m) => m.id === mode) ?? MODES[0];

  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    el.style.height = "auto";
    el.style.height = `${Math.min(el.scrollHeight, 180)}px`;
  }, [text]);

  useEffect(() => {
    if (!draft) return;
    setText(draft.text);
    const el = ref.current;
    if (el) {
      el.focus();
      el.setSelectionRange(draft.text.length, draft.text.length);
    }
  }, [draft]);

  const submit = () => {
    if (!text.trim() || streaming || disabled) return;
    onSend(text);
    setText("");
  };

  return (
    <div className="border-t border-border/80 bg-background/90 px-4 pb-2 pt-3 lg:px-8">
      <div className="mx-auto max-w-3xl">
        <div
          onDragOver={(e) => e.preventDefault()}
          onDrop={(e) => {
            e.preventDefault();
            for (const file of Array.from(e.dataTransfer.files)) onUpload(file);
          }}
          className="flex flex-col rounded-2xl border border-border bg-card shadow-sm transition-all focus-within:border-wine/60 focus-within:ring-2 focus-within:ring-wine/10"
        >
          {(attachments.length > 0 || uploading) && (
            <div className="flex flex-wrap gap-1.5 px-3 pt-2.5" data-testid="composer-attachments">
              {attachments.map((a) => (
                <span
                  key={a.document_id}
                  className="inline-flex items-center gap-1 rounded-md border border-border bg-secondary/60 py-0.5 pl-1.5 pr-0.5 text-xs text-foreground"
                >
                  <button
                    type="button"
                    onClick={() => onOpenAttachment(a)}
                    title="Preview"
                    data-testid="composer-attachment-open"
                    className="inline-flex items-center gap-1 hover:underline"
                  >
                    <FileText className="h-3 w-3 text-muted-foreground" />
                    <span className="max-w-[200px] truncate">{a.filename}</span>
                  </button>
                  <button
                    type="button"
                    aria-label={`Remove ${a.filename}`}
                    onClick={() => onRemoveAttachment(a.document_id)}
                    className="rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                </span>
              ))}
              {uploading && (
                <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
                  <Sparkles className="h-3 w-3 animate-spin" /> Filing and indexing…
                </span>
              )}
            </div>
          )}
          <textarea
            ref={ref}
            rows={1}
            value={text}
            onChange={(e) => setText(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault();
                submit();
              }
            }}
            placeholder={disabled ? "The assistant is not available: no language model is set up." : "Ask about your matters or attached documents…"}
            disabled={disabled}
            aria-label="Message"
            data-testid="chat-input"
            className="max-h-[180px] w-full resize-none bg-transparent p-3.5 text-[14.5px] leading-relaxed text-ink placeholder:text-muted-foreground focus:outline-none"
          />

          <div className="flex items-center justify-between gap-2 rounded-b-2xl border-t border-border/60 bg-muted/30 px-2 py-1.5 text-xs">
            <div className="flex min-w-0 items-center gap-1">
              <input
                ref={fileRef}
                type="file"
                accept=".pdf,.docx,.txt"
                multiple
                className="hidden"
                onChange={(e) => {
                  const picked = Array.from(e.target.files ?? []);
                  e.target.value = "";
                  for (const file of picked) onUpload(file);
                }}
              />
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    title="Attach"
                    className="flex items-center gap-1 rounded-lg px-2 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <Paperclip className="h-4 w-4" />
                    <span className="text-xs font-medium">Attach</span>
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-56">
                  <DropdownMenuItem disabled={uploading} onSelect={() => fileRef.current?.click()}>
                    <FileText className="mr-2 h-3.5 w-3.5 text-muted-foreground" />
                    {uploading ? "Filing document…" : "Upload a file"}
                  </DropdownMenuItem>
                  <DropdownMenuItem onSelect={onPickDocuments}>
                    <Search className="mr-2 h-3.5 w-3.5" />
                    Choose firm documents
                  </DropdownMenuItem>
                </DropdownMenuContent>
              </DropdownMenu>

              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <button
                    type="button"
                    data-testid="chat-mode"
                    title="How the answer is written"
                    className="flex min-w-0 items-center gap-1 rounded-lg px-2 py-1.5 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
                  >
                    <span className="text-xs">Mode:</span>
                    <span className="truncate text-xs font-semibold text-foreground">{current.label}</span>
                    <Icon name="expand_more" style={{ fontSize: 16 }} />
                  </button>
                </DropdownMenuTrigger>
                <DropdownMenuContent align="start" side="top" className="w-72">
                  {MODES.map((m) => (
                    <DropdownMenuItem
                      key={m.id}
                      onSelect={() => onMode(m.id)}
                      data-testid={`chat-mode-${m.id}`}
                      className="flex items-start gap-2 py-2"
                    >
                      <Check className={cn("mt-0.5 h-3.5 w-3.5 shrink-0", m.id === mode ? "text-wine" : "invisible")} />
                      <span>
                        <span className="block text-[13px] font-semibold text-foreground">{m.label}</span>
                        <span className="block text-[12px] text-muted-foreground">{m.description}</span>
                      </span>
                    </DropdownMenuItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>
            </div>

            {streaming ? (
              <button
                type="button"
                onClick={onStop}
                data-testid="chat-stop"
                className="inline-flex items-center gap-1 rounded-xl bg-destructive px-3 py-1.5 text-xs font-semibold text-destructive-foreground shadow-2xs hover:opacity-90"
              >
                <Icon name="stop" style={{ fontSize: 16 }} />
                <span>Stop</span>
              </button>
            ) : (
              <button
                type="button"
                onClick={submit}
                disabled={!text.trim() || disabled}
                data-testid="chat-send"
                className="inline-flex items-center gap-1 rounded-xl bg-primary px-3.5 py-1.5 text-xs font-semibold text-primary-foreground shadow-2xs transition-colors hover:bg-primary/90 disabled:bg-secondary disabled:text-muted-foreground disabled:shadow-none"
              >
                <span>Send</span>
                <Icon name="arrow_upward" style={{ fontSize: 16 }} />
              </button>
            )}
          </div>
        </div>
        <p className="mt-1.5 flex items-center justify-center gap-1.5 text-center text-xs text-muted-foreground" data-testid="chat-review-note">
          <ShieldCheck className="h-3 w-3 shrink-0" />
          <span>
            Answers are AI-generated; check the cited sources before relying on them.
            <span className="hidden sm:inline"> Shift+Enter adds a new line.</span>
          </span>
        </p>
      </div>
    </div>
  );
}
