import { Fragment, type ReactNode } from "react";

/**
 * Institutional-grade legal Markdown parser: paragraphs, headings, lists,
 * tables, block quotes, bold, italic, code, and clickable [N] citation markers.
 */
export function Markdown({ text, renderCitation }: { text: string; renderCitation?: (n: number) => ReactNode }) {
  const blocks: ReactNode[] = [];
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  let i = 0;

  const inline = (s: string) => renderInline(s, renderCitation);

  while (i < lines.length) {
    const line = lines[i];
    if (!line.trim()) {
      i++;
      continue;
    }

    // Markdown Table Detection
    if (line.trim().startsWith("|") && line.trim().endsWith("|")) {
      const tableLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith("|")) {
        tableLines.push(lines[i]);
        i++;
      }
      const tableNode = renderTable(tableLines, blocks.length, inline);
      if (tableNode) {
        blocks.push(tableNode);
        continue;
      }
    }

    // Quote Block / Legal Clause Callout
    if (line.trim().startsWith(">")) {
      const quoteLines: string[] = [];
      while (i < lines.length && lines[i].trim().startsWith(">")) {
        quoteLines.push(lines[i].replace(/^>\s?/, ""));
        i++;
      }
      blocks.push(
        <div
          key={blocks.length}
          className="my-3 rounded-r-md border-l-2 border-wine/70 bg-wine-soft/30 px-3.5 py-2 font-serif text-[13px] italic leading-relaxed text-ink"
        >
          {inline(quoteLines.join(" "))}
        </div>
      );
      continue;
    }

    // Headings
    const h3Match = line.match(/^###\s+(.*)$/);
    if (h3Match) {
      blocks.push(
        <h3 key={blocks.length} className="mt-4 mb-2 font-display text-base font-bold tracking-tight text-ink">
          {inline(h3Match[1])}
        </h3>
      );
      i++;
      continue;
    }

    const h4Match = line.match(/^####\s+(.*)$/);
    if (h4Match) {
      blocks.push(
        <h4 key={blocks.length} className="mt-3 mb-1.5 font-sans text-sm font-semibold text-ink">
          {inline(h4Match[1])}
        </h4>
      );
      i++;
      continue;
    }

    const heading = line.match(/^(#{1,2})\s+(.*)$/);
    if (heading) {
      blocks.push(
        <h3 key={blocks.length} className="mt-4 mb-2 font-display text-lg font-bold text-ink">
          {inline(heading[2])}
        </h3>
      );
      i++;
      continue;
    }

    // Horizontal Rule
    if (/^---$/.test(line.trim())) {
      blocks.push(<hr key={blocks.length} className="my-3 border-border" />);
      i++;
      continue;
    }

    // Ordered or Unordered Lists
    if (/^\s*([-*•]|\d+[.)])\s+/.test(line)) {
      const ordered = /^\s*\d+[.)]\s+/.test(line);
      // Items separated by blank lines arrive as separate lists: keep the written number.
      const start = ordered ? Number(line.match(/\d+/)?.[0] ?? 1) : undefined;
      const items: string[] = [];
      while (i < lines.length && /^\s*([-*•]|\d+[.)])\s+/.test(lines[i])) {
        items.push(lines[i].replace(/^\s*([-*•]|\d+[.)])\s+/, ""));
        i++;
      }
      const ListTag = ordered ? "ol" : "ul";
      blocks.push(
        <ListTag key={blocks.length} start={ordered && start !== 1 ? start : undefined} className={ordered ? "my-2 list-decimal space-y-1.5 pl-6" : "my-2 list-disc space-y-1.5 pl-6"}>
          {items.map((it, j) => (
            <li key={j}>{inline(it)}</li>
          ))}
        </ListTag>
      );
      continue;
    }

    // Standard paragraph
    const para: string[] = [];
    while (
      i < lines.length &&
      lines[i].trim() &&
      !/^(#{1,4})\s+/.test(lines[i]) &&
      !/^\s*([-*•]|\d+[.)])\s+/.test(lines[i]) &&
      !lines[i].trim().startsWith("|") &&
      !lines[i].trim().startsWith(">") &&
      !/^---$/.test(lines[i].trim())
    ) {
      para.push(lines[i]);
      i++;
    }
    blocks.push(<p key={blocks.length} className="my-2 text-[15px] leading-relaxed text-ink">{inline(para.join(" "))}</p>);
  }
  return <div className="space-y-3">{blocks}</div>;
}

function renderTable(lines: string[], key: number, inline: (s: string) => ReactNode[]): ReactNode {
  if (lines.length < 2) return null;
  const headerCols = lines[0]
    .split("|")
    .map((c) => c.trim())
    .filter((c) => c !== "");
  const dataRows = lines
    .slice(2)
    .map((l) =>
      l
        .split("|")
        .map((c) => c.trim())
        .filter((c) => c !== "")
    )
    .filter((r) => r.length > 0);

  return (
    <div key={key} className="my-4 overflow-x-auto rounded-lg border border-border">
      <table className="w-full border-collapse text-left text-xs">
        <thead className="border-b border-border bg-muted/60">
          <tr>
            {headerCols.map((col, idx) => (
              <th key={idx} className="px-3 py-2 text-[11px] font-semibold uppercase tracking-wider text-ink">
                {col}
              </th>
            ))}
          </tr>
        </thead>
        <tbody className="divide-y divide-border bg-card">
          {dataRows.map((row, rIdx) => (
            <tr key={rIdx} className="hover:bg-secondary/40 transition-colors">
              {row.map((cell, cIdx) => (
                <td key={cIdx} className="px-3 py-2 align-top text-[13px] leading-normal text-foreground">
                  {inline(cell)}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function renderInline(s: string, renderCitation?: (n: number) => ReactNode): ReactNode[] {
  return s.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*|`[^`]+`|\[\d+\])/g).map((part, k) => {
    if (/^\*\*[^*]+\*\*$/.test(part)) return <strong key={k} className="font-semibold text-ink">{part.slice(2, -2)}</strong>;
    if (/^\*[^*]+\*$/.test(part)) return <em key={k} className="italic text-ink">{part.slice(1, -1)}</em>;
    if (/^`[^`]+`$/.test(part)) return <code key={k} className="rounded bg-secondary px-1.5 py-0.5 font-mono-id text-[0.88em] text-ink">{part.slice(1, -1)}</code>;
    const cite = part.match(/^\[(\d+)\]$/);
    if (cite && renderCitation) return <Fragment key={k}>{renderCitation(Number(cite[1]))}</Fragment>;
    return <Fragment key={k}>{part}</Fragment>;
  });
}
