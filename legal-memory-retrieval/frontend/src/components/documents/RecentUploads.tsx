import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { retryBatch, useRecentUploads } from "@/api/uploads";
import { Button } from "@/components/ui/button";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";

/** What the caller uploaded lately and how each file fared; failed files can be tried again. */
export function RecentUploads() {
  const recent = useRecentUploads();
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const [busy, setBusy] = useState<string | null>(null);
  const batches = recent.data ?? [];
  if (!batches.length) return null;

  const retry = async (id: string) => {
    setBusy(id);
    try {
      await retryBatch(id);
      toast("Trying the failed files again");
      queryClient.invalidateQueries({ queryKey: ["recent-uploads"] });
      queryClient.invalidateQueries({ queryKey: ["documents"] });
    } catch (err) {
      toast(firmError(err));
    } finally {
      setBusy(null);
    }
  };

  return (
    <details className="rounded-md border border-border bg-card" data-testid="recent-uploads">
      <summary className="cursor-pointer px-4 py-2.5 text-sm font-medium">
        Your recent uploads
        {batches.some((b) => b.failed > 0) && <span className="ml-2 text-destructive">some files failed</span>}
      </summary>
      <ul className="divide-y divide-border border-t border-border">
        {batches.map((b) => (
          <li key={b.batch_id} className="space-y-1 px-4 py-3 text-sm" data-testid="recent-upload">
            <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
              <span className="font-medium">{b.matter_title}</span>
              <span className="text-muted-foreground">{formatDate(b.created_at)}</span>
              <span className="text-muted-foreground">
                {b.indexed} added{b.duplicates > 0 && `, ${b.duplicates} already there`}{b.failed > 0 && `, ${b.failed} failed`}
              </span>
              {b.retryable && (
                <Button size="sm" variant="outline" className="ml-auto" disabled={busy === b.batch_id} onClick={() => retry(b.batch_id)} data-testid="retry-upload">
                  Try the failed files again
                </Button>
              )}
            </div>
            {b.files.filter((f) => f.status === "failed" || f.status === "quarantined").map((f) => (
              <p key={f.relative_path} className="text-xs text-destructive">{f.relative_path}: {f.error || "could not be processed"}</p>
            ))}
          </li>
        ))}
      </ul>
    </details>
  );
}
