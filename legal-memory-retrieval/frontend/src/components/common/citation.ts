import { cn } from "@/lib/utils";

/** The one look for a citation marker, in Ask answers and Assistant messages alike. */
export function citationChipClass(opts: { partial?: boolean; className?: string } = {}) {
  return cn(
    "mx-0.5 inline-flex items-center gap-0.5 rounded-[3px] border border-transparent bg-wine-soft px-1 align-baseline font-mono-id text-xs font-semibold text-wine transition-colors hover:bg-wine hover:text-primary-foreground",
    opts.partial && "border-dashed border-wine/60",
    opts.className,
  );
}
