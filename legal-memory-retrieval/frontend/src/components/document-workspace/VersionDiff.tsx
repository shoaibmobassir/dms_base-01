import type { ReactNode } from "react";
import type { CompareBlock, CompareResult } from "@/api/editor";
import { cn } from "@/lib/utils";

type Segment = { t: "eq" | "ins" | "del"; text: string };

/**
 * An old value and its replacement are shown as `old → new`, never run together. The stored file holds no
 * markup; this is drawn from the difference between two versions.
 */
export function Segments({ segments }: { segments: Segment[] }) {
  const out: ReactNode[] = [];
  for (let i = 0; i < segments.length; i += 1) {
    const seg = segments[i];
    const next = segments[i + 1];
    if (seg.t === "del" && next?.t === "ins") {
      out.push(
        <span key={i} className="whitespace-normal" data-testid="diff-replace">
          <del className="rounded-sm bg-red-500/10 px-0.5 text-red-900 decoration-red-500/70 dark:text-red-200">{seg.text}</del>
          <span className="mx-1 select-none text-muted-foreground" aria-hidden="true">→</span>
          <ins className="rounded-sm bg-emerald-500/10 px-0.5 text-emerald-900 no-underline dark:text-emerald-200">{next.text}</ins>
        </span>,
      );
      i += 1;
    } else if (seg.t === "del") {
      out.push(<del key={i} className="rounded-sm bg-red-500/10 px-0.5 text-red-900 decoration-red-500/70 dark:text-red-200">{seg.text}</del>);
    } else if (seg.t === "ins") {
      out.push(<ins key={i} className="rounded-sm bg-emerald-500/10 px-0.5 text-emerald-900 no-underline dark:text-emerald-200">{seg.text}</ins>);
    } else {
      out.push(<span key={i}>{seg.text}</span>);
    }
  }
  return <>{out}</>;
}

function Block({ block }: { block: CompareBlock }) {
  if (block.op === "equal") {
    return (
      <p className="px-3 py-1 text-xs text-muted-foreground" data-testid="diff-unchanged">
        {block.count} unchanged paragraph{block.count === 1 ? "" : "s"}
      </p>
    );
  }
  if (block.op === "replace") {
    return (
      <p className="rounded-md border border-border bg-card px-3 py-2 text-sm leading-relaxed" data-testid="diff-changed">
        <Segments segments={block.segments} />
      </p>
    );
  }
  const added = block.op === "insert";
  return (
    <p
      className={cn("rounded-md border px-3 py-2 text-sm leading-relaxed",
        added ? "border-emerald-500/30 bg-emerald-500/5" : "border-red-500/30 bg-red-500/5")}
      data-testid={added ? "diff-added" : "diff-removed"}
    >
      <span className="mr-2 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">{added ? "Added" : "Removed"}</span>
      {added ? <ins className="no-underline">{block.new}</ins> : <del className="decoration-red-500/70">{block.old}</del>}
    </p>
  );
}

export function VersionDiff({ result }: { result: CompareResult }) {
  const { stats } = result;
  const changed = stats.changed + stats.inserted + stats.deleted;
  return (
    <div className="space-y-2" data-testid="version-diff">
      <p className="text-xs text-muted-foreground" data-testid="diff-stats">
        {changed === 0
          ? "No differences."
          : [
              typeof stats.words_added === "number" ? `+${stats.words_added} words` : null,
              typeof stats.words_removed === "number" ? `−${stats.words_removed} words` : null,
              `${changed} paragraph${changed === 1 ? "" : "s"} changed`,
            ].filter(Boolean).join(" · ")}
      </p>
      {result.blocks.map((b, i) => <Block key={i} block={b} />)}
    </div>
  );
}
