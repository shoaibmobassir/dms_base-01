import { useMemo, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  editErrorMessage,
  getPrivacy,
  getShareTargets,
  setPrivacy,
  type DocShare,
  type Visibility,
} from "@/api/editor";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Icon } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const LABEL: Record<Visibility, string> = { matter: "Matter", restricted: "Restricted", private: "Private" };
const ICON: Record<Visibility, string> = { matter: "group", restricted: "shield_lock", private: "lock" };
const HELP: Record<Visibility, string> = {
  matter: "Everyone who can see the matter can see this document.",
  restricted: "Only the people and teams below, plus the matter's lead and managers.",
  private: "Only you and the people and teams below.",
};

/** Who can see a document: a chip, and (for its owner or a matter manager) a dialog to change it. */
export function PrivacyControl({ documentId }: { documentId: string }) {
  const { identityKey } = useApp();
  const key = [identityKey, "doc-privacy", documentId];
  const privacy = useQuery({ queryKey: key, queryFn: () => getPrivacy(documentId), enabled: Boolean(identityKey) });
  const [open, setOpen] = useState(false);
  if (!privacy.data) return null;
  const v = privacy.data.visibility;
  return (
    <>
      <button
        type="button"
        onClick={() => setOpen(true)}
        className={cn(
          "inline-flex items-center gap-1 rounded-full border px-2.5 py-1 text-xs",
          v === "matter" ? "border-border text-muted-foreground" : "border-amber-300 bg-amber-50 text-amber-900 dark:bg-amber-950/30 dark:text-amber-200",
        )}
        title={HELP[v]}
        data-testid="privacy-chip"
      >
        <Icon name={ICON[v]} style={{ fontSize: 14 }} /> {LABEL[v]}
      </button>
      {open && <PrivacyDialog documentId={documentId} queryKey={key} onClose={() => setOpen(false)} />}
    </>
  );
}

function PrivacyDialog({ documentId, queryKey, onClose }: { documentId: string; queryKey: unknown[]; onClose: () => void }) {
  const { toast } = useApp();
  const queryClient = useQueryClient();
  const current = queryClient.getQueryData<Awaited<ReturnType<typeof getPrivacy>>>(queryKey);
  const targets = useQuery({ queryKey: [...queryKey, "targets"], queryFn: () => getShareTargets(documentId), enabled: Boolean(current?.can_change) });
  const [visibility, setVisibility] = useState<Visibility>(current?.visibility ?? "matter");
  const [shares, setShares] = useState<DocShare[]>(current?.shares ?? []);
  const [filter, setFilter] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const canChange = Boolean(current?.can_change);

  const has = (t: DocShare["principal_type"], id: string) => shares.some((s) => s.principal_type === t && s.principal_id === id);
  const toggle = (t: DocShare["principal_type"], id: string, name: string) =>
    setShares((cur) => (has(t, id) ? cur.filter((s) => !(s.principal_type === t && s.principal_id === id)) : [...cur, { principal_type: t, principal_id: id, level: "read", name }]));
  const setLevel = (s: DocShare, level: DocShare["level"]) =>
    setShares((cur) => cur.map((x) => (x.principal_type === s.principal_type && x.principal_id === s.principal_id ? { ...x, level } : x)));

  const q = filter.trim().toLowerCase();
  const people = useMemo(
    () => (targets.data?.people ?? []).filter((p) => p.member_id !== current?.owner?.member_id && (!q || p.name.toLowerCase().includes(q))).slice(0, 40),
    [targets.data, q, current?.owner?.member_id],
  );
  const teams = useMemo(() => (targets.data?.teams ?? []).filter((t) => !q || t.name.toLowerCase().includes(q)), [targets.data, q]);

  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      const out = await setPrivacy(documentId, {
        visibility,
        shares: visibility === "matter" ? [] : shares.map(({ principal_type, principal_id, level }) => ({ principal_type, principal_id, level })),
        row_version: current?.row_version ?? 0,
      });
      queryClient.setQueryData(queryKey, out);
      // Lists, matter pages and search now see the document differently.
      await queryClient.invalidateQueries({ predicate: (qq) => qq.queryKey.includes("documents") || qq.queryKey.includes("matter") });
      toast(visibility === "matter" ? "The document follows its matter again" : `The document is now ${LABEL[visibility].toLowerCase()}`);
      onClose();
    } catch (err) {
      setError(editErrorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="privacy-dialog">
        <DialogHeader>
          <DialogTitle>Who can see this document</DialogTitle>
          <DialogDescription>
            Document privacy narrows matter access; it never opens a document to people outside the matter.
            {current?.owner && <> Owner: {current.owner.name}.</>}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3">
          <div role="radiogroup" className="grid gap-2">
            {(["matter", "restricted", "private"] as Visibility[]).map((v) => (
              <label
                key={v}
                className={cn("flex cursor-pointer items-start gap-2 rounded-md border p-2.5 text-sm",
                  visibility === v ? "border-primary bg-secondary/60" : "border-border", !canChange && "cursor-default opacity-70")}
              >
                <input type="radio" name="visibility" value={v} checked={visibility === v} disabled={!canChange}
                  onChange={() => setVisibility(v)} className="mt-0.5" data-testid={`privacy-${v}`} />
                <span>
                  <span className="flex items-center gap-1 font-medium"><Icon name={ICON[v]} style={{ fontSize: 15 }} /> {LABEL[v]}</span>
                  <span className="text-xs text-muted-foreground">{HELP[v]}</span>
                </span>
              </label>
            ))}
          </div>

          {visibility !== "matter" && (
            <div className="space-y-2">
              {shares.length > 0 && (
                <ul className="space-y-1" data-testid="privacy-shares">
                  {shares.map((s) => (
                    <li key={`${s.principal_type}:${s.principal_id}`} className="flex items-center gap-2 text-sm">
                      <Icon name={s.principal_type === "team" ? "groups" : "person"} style={{ fontSize: 16 }} />
                      <span className="flex-1 truncate">{s.name ?? s.principal_id}</span>
                      <select value={s.level} disabled={!canChange} onChange={(e) => setLevel(s, e.target.value as DocShare["level"])}
                        className="h-7 rounded border border-border bg-background px-1 text-xs">
                        <option value="read">Can read</option>
                        <option value="edit">Can edit</option>
                      </select>
                      {canChange && (
                        <button type="button" aria-label="Remove" className="rounded p-0.5 hover:bg-secondary"
                          onClick={() => toggle(s.principal_type, s.principal_id, s.name ?? "")}>
                          <Icon name="close" style={{ fontSize: 14 }} />
                        </button>
                      )}
                    </li>
                  ))}
                </ul>
              )}
              {canChange && (
                <>
                  <Input placeholder="Add people or teams…" value={filter} onChange={(e) => setFilter(e.target.value)} data-testid="privacy-filter" />
                  <div className="max-h-48 overflow-y-auto rounded-md border border-border">
                    {teams.map((t) => (
                      <button key={t.team_id} type="button" onClick={() => toggle("team", t.team_id, t.name)}
                        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-secondary">
                        <Icon name={has("team", t.team_id) ? "check_box" : "check_box_outline_blank"} style={{ fontSize: 16 }} />
                        <Icon name="groups" style={{ fontSize: 15 }} /> {t.name}
                        <span className="ml-auto text-xs text-muted-foreground">{t.members}</span>
                      </button>
                    ))}
                    {people.map((p) => (
                      <button key={p.member_id} type="button" onClick={() => toggle("member", p.member_id, p.name)}
                        className="flex w-full items-center gap-2 px-2 py-1.5 text-left text-sm hover:bg-secondary"
                        data-testid="privacy-person">
                        <Icon name={has("member", p.member_id) ? "check_box" : "check_box_outline_blank"} style={{ fontSize: 16 }} />
                        {p.name}
                        <span className="ml-auto text-xs text-muted-foreground">{p.role}</span>
                      </button>
                    ))}
                  </div>
                </>
              )}
            </div>
          )}

          {!canChange && (
            <p className="text-xs text-muted-foreground">
              Only the document's owner (or, unless it is private, a matter manager) can change who sees it.
            </p>
          )}
          {error && <p className="text-sm text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>{canChange ? "Cancel" : "Close"}</Button>
            {canChange && <Button disabled={busy} onClick={() => void save()} data-testid="privacy-save">Save</Button>}
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
