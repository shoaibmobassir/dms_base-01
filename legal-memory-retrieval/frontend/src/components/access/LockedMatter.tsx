import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { requestAccess, useMatterAccessStatus } from "@/api/access";
import { Button } from "@/components/ui/button";
import { EmptyState, MonoId, PageHeader } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";

/** Shown instead of a matter the member cannot open. Hidden matters stay indistinguishable from missing ones. */
export function LockedMatter({ matterId }: { matterId: string }) {
  const status = useMatterAccessStatus(matterId, true);
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [reason, setReason] = useState("");
  const [level, setLevel] = useState<"read" | "edit">("read");
  const [busy, setBusy] = useState(false);

  if (status.isPending) return <p className="text-sm text-muted-foreground">Checking access…</p>;
  if (status.isError || !status.data) {
    return <EmptyState icon="search_off" title="Matter not found" description="It does not exist or is outside your access scope." />;
  }
  const s = status.data;
  const submit = async () => {
    setBusy(true);
    try {
      await requestAccess(matterId, { level, reason });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "matter-access-status", matterId] });
      toast("Access requested — the matter's managers have been asked");
    } catch (err) {
      toast(err instanceof Error ? err.message : "The request was not sent");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="locked-matter">
      <PageHeader eyebrow="Matter · access needed" title={s.title}>
        <div className="mt-3"><MonoId className="text-sm">{s.matter_code}</MonoId></div>
      </PageHeader>
      <div className="max-w-xl rounded-lg border border-border bg-card p-6">
        {s.pending_request_id ? (
          <p className="text-sm">Your request is waiting for a decision by the matter's managers.</p>
        ) : s.can_request ? (
          <div className="space-y-3">
            <p className="text-sm">This matter is limited to its team. Tell the managers why you need it.</p>
            <select
              value={level}
              onChange={(e) => setLevel(e.target.value as "read" | "edit")}
              className="h-9 rounded-md border border-input bg-transparent px-2 text-sm"
              aria-label="Access level"
            >
              <option value="read">Read</option>
              <option value="edit">Edit</option>
            </select>
            <textarea
              value={reason}
              onChange={(e) => setReason(e.target.value)}
              rows={3}
              placeholder="Reason (e.g. covering the hearing on 3 October)"
              className="w-full rounded-md border border-input bg-transparent p-2 text-sm"
              data-testid="access-request-reason"
            />
            <Button disabled={busy || reason.trim().length < 3} onClick={() => void submit()} data-testid="access-request-submit">
              Request access
            </Button>
          </div>
        ) : (
          <p className="text-sm">You cannot open this matter.</p>
        )}
      </div>
    </div>
  );
}
