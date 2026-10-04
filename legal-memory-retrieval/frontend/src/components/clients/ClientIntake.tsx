import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  createClient,
  decideConflict,
  firmError,
  listConflictChecks,
  runConflictCheck,
  type ConflictCheck,
  type ConflictHit,
} from "@/api/firm";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Icon, SectionLabel } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const inputCls = "w-full rounded-md border border-border bg-card px-3 py-2 text-sm";

function Hit({ hit }: { hit: ConflictHit }) {
  if (hit.kind === "adverse_party" && "redacted" in hit && hit.redacted) {
    return (
      <li className="flex items-start gap-2 rounded-md border border-warning/60 bg-warning-soft p-2 text-sm" data-testid="conflict-hit">
        <Icon name="shield_lock" style={{ fontSize: 16 }} /> <span><b>{hit.query}</b>: {hit.note}</span>
      </li>
    );
  }
  if (hit.kind === "existing_client") {
    return (
      <li className="flex items-start gap-2 rounded-md border border-border p-2 text-sm" data-testid="conflict-hit">
        <Icon name="apartment" style={{ fontSize: 16 }} />
        <span><b>{hit.query}</b> matches existing client <Link className="underline" to={`/clients/${hit.client_id}`}>{hit.name}</Link> ({hit.status})</span>
      </li>
    );
  }
  return (
    <li className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-2 text-sm" data-testid="conflict-hit">
      <Icon name="gavel" style={{ fontSize: 16 }} />
      <span>
        <b>{hit.query}</b> is the other side in <Link className="underline" to={`/matters/${hit.matter_id}`}>{hit.matter_code}</Link> — {hit.title}
        {" "}(for {hit.client_name})
      </span>
    </li>
  );
}

const STATUS_TEXT: Record<ConflictCheck["status"], string> = {
  clear: "Clear — no matches",
  awaiting_risk: "Matches found — waiting for Risk",
  waived: "Waived by Risk",
  conflict: "Conflict — cannot act",
};

/** Intake: conflict-check the names, then open the client against the check. */
export function NewClientDialog({ open, onClose }: { open: boolean; onClose: () => void }) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [name, setName] = useState("");
  const [others, setOthers] = useState("");
  const [industry, setIndustry] = useState("");
  const [check, setCheck] = useState<ConflictCheck | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const doCheck = async () => {
    setBusy(true);
    setError(null);
    try {
      const names = [name, ...others.split("\n")].map((s) => s.trim()).filter(Boolean);
      setCheck(await runConflictCheck(names, "Client intake"));
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  const doCreate = async () => {
    if (!check) return;
    setBusy(true);
    setError(null);
    try {
      const c = await createClient({ name: name.trim(), check_id: check.check_id, industry: industry || undefined });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "clients"] });
      toast(c.status === "active" ? `${c.name} is now a client` : `${c.name} added as prospective until Risk decides`);
      onClose();
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="new-client-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">New client</DialogTitle>
          <DialogDescription>
            The names are checked against every client and every matter's other side, across the whole firm.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <input className={inputCls} placeholder="Client name" aria-label="Client name" value={name}
            onChange={(e) => { setName(e.target.value); setCheck(null); }} data-testid="new-client-name" />
          <textarea className={`${inputCls} min-h-16`} placeholder="Group companies and the other side, one per line (optional)" value={others}
            onChange={(e) => { setOthers(e.target.value); setCheck(null); }} />
          {!check ? (
            <div className="flex justify-end gap-2">
              <Button variant="outline" onClick={onClose}>Cancel</Button>
              <Button disabled={busy || !name.trim()} onClick={() => void doCheck()} data-testid="new-client-check">
                {busy ? "Checking…" : "Run conflict check"}
              </Button>
            </div>
          ) : (
            <>
              <div className={cn("rounded-md px-3 py-2 font-medium",
                check.status === "clear" || check.status === "waived" ? "bg-success-soft text-success-ink" :
                check.status === "conflict" ? "bg-destructive/10 text-destructive" : "bg-warning-soft text-warning-ink")}
                data-testid="new-client-status">
                {STATUS_TEXT[check.status]}
              </div>
              {check.results.length > 0 && <ul className="space-y-1.5">{check.results.map((h, i) => <Hit key={i} hit={h} />)}</ul>}
              <input className={inputCls} placeholder="Industry (optional)" aria-label="Industry" value={industry} onChange={(e) => setIndustry(e.target.value)} />
              <div className="flex justify-end gap-2">
                <Button variant="outline" onClick={onClose}>Cancel</Button>
                <Button disabled={busy || check.status === "conflict"} onClick={() => void doCreate()} data-testid="new-client-create">
                  {check.status === "awaiting_risk" ? "Add as prospective" : "Add client"}
                </Button>
              </div>
            </>
          )}
          {error && <p className="text-sm text-destructive" data-testid="form-error">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Risk's queue: checks with matches waiting for a decision. */
export function ConflictQueue() {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const key = [identityKey, "conflicts", "to_decide"];
  const checks = useQuery({ queryKey: key, queryFn: () => listConflictChecks("to_decide"), enabled: Boolean(identityKey) });
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);
  const decide = async (id: string, decision: "clear" | "conflict" | "waived") => {
    setError(null);
    try {
      await decideConflict(id, decision, notes[id] ?? "");
      await queryClient.invalidateQueries({ queryKey: key });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "clients"] });
      toast(`Recorded: ${decision}`);
    } catch (err) {
      setError(firmError(err));
    }
  };
  if (!checks.data?.length) return null;
  return (
    <section className="space-y-3 rounded-lg border border-warning/60 bg-warning-soft p-4" data-testid="conflict-queue">
      <SectionLabel>Conflict checks waiting for Risk ({checks.data.length})</SectionLabel>
      {checks.data.map((c) => (
        <div key={c.check_id} className="space-y-2 rounded-md border border-border bg-card p-3" data-testid="conflict-queue-item">
          <div className="text-sm font-medium">{c.names.join(" · ")}</div>
          <ul className="space-y-1.5">{c.results.map((h, i) => <Hit key={i} hit={h} />)}</ul>
          <input className={inputCls} placeholder="Reasons (required to waive or declare a conflict)" value={notes[c.check_id] ?? ""}
            onChange={(e) => setNotes((n) => ({ ...n, [c.check_id]: e.target.value }))} />
          <div className="flex gap-2">
            <Button size="sm" onClick={() => void decide(c.check_id, "clear")}>Clear</Button>
            <Button size="sm" variant="outline" onClick={() => void decide(c.check_id, "waived")}>Waive</Button>
            <Button size="sm" variant="outline" className="text-destructive" onClick={() => void decide(c.check_id, "conflict")}>Conflict</Button>
          </div>
        </div>
      ))}
      {error && <p className="text-sm text-destructive">{error}</p>}
    </section>
  );
}
