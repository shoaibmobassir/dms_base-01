import { useEffect, useRef, useState } from "react";
import { useDocumentSearch, type BlockMatch } from "@/api/resources";
import { Icon } from "@/components/common/primitives";
import { useDebounced } from "@/lib/use-debounced";

/** Find a phrase anywhere in the open version, then jump to the page or part that holds it. */
export function FindInDocument({
  documentId,
  versionId,
  onPick,
  onClose,
}: {
  documentId: string;
  versionId: string | undefined;
  onPick: (match: BlockMatch) => void;
  onClose: () => void;
}) {
  const [text, setText] = useState("");
  const q = useDebounced(text.trim(), 250);
  const result = useDocumentSearch(documentId, versionId, q);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => input.current?.focus(), []);

  const matches = result.data?.matches ?? [];
  const total = result.data?.total ?? 0;

  return (
    <div className="border-b border-border bg-card px-3 py-2" data-testid="find-in-document" role="search">
      <div className="mx-auto flex max-w-3xl items-center gap-2">
        <Icon name="search" className="text-muted-foreground" style={{ fontSize: 18 }} />
        <input
          ref={input}
          value={text}
          onChange={(e) => setText(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "Enter" && matches[0]) onPick(matches[0]);
          }}
          placeholder="Find in this document"
          aria-label="Find in this document"
          data-testid="find-input"
          className="min-w-0 flex-1 bg-transparent py-1 text-sm focus:outline-none"
        />
        {q.length >= 2 && !result.isPending && (
          <span className="shrink-0 text-xs text-muted-foreground" role="status" data-testid="find-count">
            {total === 0 ? "No matches" : total > matches.length ? `${matches.length} of ${total} matches` : `${total} ${total === 1 ? "match" : "matches"}`}
          </span>
        )}
        <button type="button" onClick={onClose} aria-label="Close search" className="rounded p-1.5 text-muted-foreground hover:bg-secondary">
          <Icon name="close" style={{ fontSize: 18 }} />
        </button>
      </div>
      {matches.length > 0 && (
        <ul className="mx-auto mt-2 max-h-56 max-w-3xl divide-y divide-border overflow-y-auto rounded-md border border-border" data-testid="find-results">
          {matches.map((m) => (
            <li key={m.block_id}>
              <button type="button" onClick={() => onPick(m)} className="block w-full px-3 py-2 text-left text-sm hover:bg-secondary" data-testid="find-result">
                <span className="block text-foreground">{highlight(m.snippet, q)}</span>
                <span className="block text-xs text-muted-foreground">
                  {[m.page_number ? `Page ${m.page_number}` : null, m.section_title].filter(Boolean).join(" · ") || "Open at this passage"}
                </span>
              </button>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function highlight(snippet: string, q: string) {
  const at = snippet.toLowerCase().indexOf(q.toLowerCase());
  if (at < 0) return snippet;
  return (
    <>
      {snippet.slice(0, at)}
      <mark className="rounded-sm bg-highlight px-0.5 text-ink">{snippet.slice(at, at + q.length)}</mark>
      {snippet.slice(at + q.length)}
    </>
  );
}
