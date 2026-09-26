import { useEffect, useState } from "react";
import { useParams } from "react-router-dom";
import { compareVersions, useDocument, useDocumentVersions } from "@/api/resources";
import { Action, EmptyState, MonoId, PageHeader, SectionLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { cn } from "@/lib/utils";

export function DocumentHistoryPage() {
  const { id = "" } = useParams();
  const doc = useDocument(id);
  const versions = useDocumentVersions(id);
  const [selected, setSelected] = useState("");
  const [diff, setDiff] = useState<{ text: string; error?: string } | null>(null);

  const rows = versions.data ?? [];
  const current = rows.find((v) => v.version_id === selected) ?? rows[0];

  useEffect(() => {
    setDiff(null);
    if (!current || rows.length < 2) return;
    // Compare the selected version with the one before it (list is newest first).
    const idx = rows.findIndex((v) => v.version_id === current.version_id);
    const previous = rows[idx + 1];
    if (!previous) return;
    let cancelled = false;
    compareVersions(id, current.version_id, previous.version_id)
      .then((res) => !cancelled && setDiff({ text: res.diff ?? "" }))
      .catch((err) => !cancelled && setDiff({ text: "", error: err instanceof Error ? err.message : "Diff failed" }));
    return () => {
      cancelled = true;
    };
  }, [id, current, rows]);

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Draft evolution"
        title={doc.data?.title ?? id}
        subtitle="How this document changed over time — who changed it, when, and what changed."
        actions={
          <Action to={`/documents/${id}`} icon="description">
            Open document
          </Action>
        }
      >
        <div className="mt-3">
          <MonoId className="text-sm">{id}</MonoId>
        </div>
      </PageHeader>

      <QueryState
        query={versions}
        isEmpty={(v) => v.length === 0}
        empty={<EmptyState icon="account_tree" title="No recorded versions" description="This document has a single, unversioned text." />}
      >
        {() => (
          <div className="grid gap-8 lg:grid-cols-[320px_minmax(0,1fr)]">
            <div>
              <SectionLabel>Versions</SectionLabel>
              <ol className="relative space-y-1 border-l border-border pl-5">
                {rows.map((v) => (
                  <li key={v.version_id} className="relative">
                    <span className="absolute -left-[23px] top-3 h-2 w-2 rounded-full bg-wine" />
                    <button
                      type="button"
                      onClick={() => setSelected(v.version_id)}
                      className={cn(
                        "w-full rounded-md px-3 py-2 text-left text-sm",
                        current?.version_id === v.version_id ? "bg-wine-soft text-wine" : "hover:bg-secondary",
                      )}
                    >
                      <div className="font-medium">{v.version_label || `Version ${v.version_number ?? ""}`}</div>
                      <div className="text-xs text-muted-foreground">
                        {[v.author_name, v.version_status, v.created_at?.slice(0, 10)].filter(Boolean).join(" · ")}
                      </div>
                    </button>
                  </li>
                ))}
              </ol>
            </div>
            <div>
              <SectionLabel>Changes from the previous version</SectionLabel>
              {rows.length < 2 && <p className="text-sm text-muted-foreground">Only one version exists.</p>}
              {diff?.error && <p className="text-sm text-destructive">{diff.error}</p>}
              {diff && !diff.error && (
                <pre className="overflow-x-auto whitespace-pre-wrap rounded-lg border border-border bg-card p-4 text-xs" data-testid="version-diff">
                  {diff.text || "No textual differences."}
                </pre>
              )}
            </div>
          </div>
        )}
      </QueryState>
    </div>
  );
}
