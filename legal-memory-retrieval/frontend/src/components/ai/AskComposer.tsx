import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/common/primitives";

export function AskComposer({
  examples = [],
  scopeLabel,
  large,
  placeholder = "Ask anything about the firm's work…",
}: {
  examples?: string[];
  /** A matter code / client name the question is about; sent along with the question. */
  scopeLabel?: string;
  large?: boolean;
  placeholder?: string;
}) {
  const [q, setQ] = useState("");
  const navigate = useNavigate();

  const submit = (text?: string) => {
    const query = (text ?? q).trim();
    if (!query) return;
    navigate(`/ask?q=${encodeURIComponent(query)}${scopeLabel ? `&scope=${encodeURIComponent(scopeLabel)}` : ""}`);
  };

  return (
    <div className={cn("animate-rise", large && "mx-auto max-w-3xl")} data-testid="ask-composer">
      <div className="rounded-xl border border-border bg-card shadow-[0_1px_0_rgba(0,0,0,0.02)] transition-all focus-within:border-wine/50 focus-within:ring-1 focus-within:ring-wine/20">
        <div className="flex items-start gap-3 px-5 pt-5">
          <Icon name="menu_book" className="mt-1 text-wine" />
          <textarea
            value={q}
            onChange={(e) => setQ(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            rows={large ? 3 : 2}
            placeholder={placeholder}
            aria-label="Question"
            data-testid="ask-input"
            className="w-full resize-none bg-transparent font-display text-xl leading-snug text-ink placeholder:font-sans placeholder:text-lg placeholder:font-normal placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
        <div className="flex items-center justify-between px-4 py-2.5">
          {scopeLabel ? (
            <span className="inline-flex items-center gap-1.5 rounded-md bg-wine-soft px-2.5 py-1 text-xs font-semibold text-wine">
              <Icon name="target" style={{ fontSize: 15 }} /> {scopeLabel}
            </span>
          ) : (
            <span className="text-xs text-muted-foreground">Searches everything you have access to</span>
          )}
          <button
            type="button"
            onClick={() => submit()}
            disabled={!q.trim()}
            data-testid="ask-submit"
            className="inline-flex items-center gap-1.5 rounded-md bg-primary px-4 py-2 text-sm font-semibold text-primary-foreground transition-all hover:opacity-90 active:scale-[0.98] disabled:opacity-50"
          >
            Ask the Firm <Icon name="arrow_forward" style={{ fontSize: 16 }} />
          </button>
        </div>
      </div>
      {examples.length > 0 && (
        <div className="mt-5">
          <div className="meta-label mb-2.5">Try asking</div>
          <div className="flex flex-col gap-px">
            {examples.map((ex) => (
              <button
                key={ex}
                type="button"
                onClick={() => submit(ex)}
                data-testid="ask-example"
                className="group flex items-center gap-3 rounded-md px-3 py-2.5 text-left text-[15px] text-foreground transition-colors hover:bg-secondary"
              >
                <Icon name="chevron_right" className="text-muted-foreground transition-colors group-hover:text-wine" style={{ fontSize: 18 }} />
                <span className="group-hover:text-wine">{ex}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
