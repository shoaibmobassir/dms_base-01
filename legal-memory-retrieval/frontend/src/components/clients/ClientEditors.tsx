import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { addClientNote, firmError, updateClient } from "@/api/firm";
import type { ClientDetail, ClientNote } from "@/api/types";
import { Field, fieldControl } from "@/components/common/Field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";

const list = (text: string) => text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

/** Run a client write and refresh what it changes. */
function useClientWrite(clientId: string) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await queryClient.invalidateQueries({ queryKey: [identityKey, "client", clientId] });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "clients"] });
      toast(done);
      return true;
    } catch (err) {
      setError(firmError(err));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error };
}

const STATUS_LABEL: Record<string, string> = { active: "Active", on_hold: "On hold", inactive: "Inactive" };

/** Edit a client's details and its standing (active, on hold, inactive; inactive needs every matter closed). */
export function EditClientDialog({ client, onClose }: { client: ClientDetail & { status?: string }; onClose: () => void }) {
  const { run, busy, error } = useClientWrite(client.client_id);
  const [name, setName] = useState(client.name);
  const [industry, setIndustry] = useState(client.industry ?? "");
  const [hq, setHq] = useState(client.headquarters ?? "");
  const [aliases, setAliases] = useState((client.aliases ?? []).join(", "));
  const [status, setStatus] = useState<string>(client.status && STATUS_LABEL[client.status] ? client.status : "active");
  const intake = client.status === "prospective" || client.status === "declined";
  const submit = async () => {
    const body: Record<string, unknown> = { name: name.trim(), industry, headquarters: hq, aliases: list(aliases) };
    if (!intake && status !== client.status) body.status = status;
    if (await run(() => updateClient(client.client_id, body), "Client updated")) onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="edit-client-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Edit client</DialogTitle>
          <DialogDescription>Changes are recorded in the audit trail.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <Field label="Name">{(f) => <input {...f} className={fieldControl} value={name} onChange={(e) => setName(e.target.value)} data-testid="edit-client-name" />}</Field>
          <div className="grid grid-cols-2 gap-3">
            <Field label="Industry">{(f) => <input {...f} className={fieldControl} value={industry} onChange={(e) => setIndustry(e.target.value)} />}</Field>
            <Field label="Headquarters">{(f) => <input {...f} className={fieldControl} value={hq} onChange={(e) => setHq(e.target.value)} />}</Field>
          </div>
          <Field label="Other names" hint="Separate with commas. Conflict checks search these too.">
            {(f) => <input {...f} className={fieldControl} value={aliases} onChange={(e) => setAliases(e.target.value)} />}
          </Field>
          <Field label="Standing" hint={intake ? "Still in intake: its conflict check decides this." : "Inactive needs every matter for this client closed."}>
            {(f) => (
              <select {...f} className={fieldControl} value={intake ? client.status : status} disabled={intake} onChange={(e) => setStatus(e.target.value)} data-testid="edit-client-status">
                {intake ? <option value={client.status}>{client.status}</option> : Object.entries(STATUS_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </select>
            )}
          </Field>
          {error && <p className="text-destructive" role="alert" data-testid="form-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || !name.trim()} onClick={() => void submit()} data-testid="edit-client-save">{busy ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

const KIND_LABEL: Record<ClientNote["kind"], string> = { prefers: "Prefers", avoid: "Avoid", terms: "Commercial terms" };

/** A note about how the client likes to work; tie it to one of their matters when it came from one. */
export function AddNoteDialog({ client, onClose }: { client: ClientDetail; onClose: () => void }) {
  const { run, busy, error } = useClientWrite(client.client_id);
  const [kind, setKind] = useState<ClientNote["kind"]>("prefers");
  const [text, setText] = useState("");
  const [matter, setMatter] = useState("");
  const submit = async () => {
    if (await run(() => addClientNote(client.client_id, { kind, text: text.trim(), source_matter_id: matter || null }), "Note added")) onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="add-note-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Add a note</DialogTitle>
          <DialogDescription>Colleagues see this on the client page and in Ask the Firm.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <Field label="Kind">
            {(f) => (
              <select {...f} className={fieldControl} value={kind} onChange={(e) => setKind(e.target.value as ClientNote["kind"])} data-testid="note-kind">
                {(Object.keys(KIND_LABEL) as ClientNote["kind"][]).map((k) => <option key={k} value={k}>{KIND_LABEL[k]}</option>)}
              </select>
            )}
          </Field>
          <Field label="Note">{(f) => <textarea {...f} className={`${fieldControl} min-h-24`} value={text} onChange={(e) => setText(e.target.value)} data-testid="note-text" />}</Field>
          {client.matters.length > 0 && (
            <Field label="Where it came from" hint="Optional.">
              {(f) => (
                <select {...f} className={fieldControl} value={matter} onChange={(e) => setMatter(e.target.value)}>
                  <option value="">Not tied to a matter</option>
                  {client.matters.map((m) => <option key={m.matter_id} value={m.matter_id}>{m.matter_code}, {m.title}</option>)}
                </select>
              )}
            </Field>
          )}
          {error && <p className="text-destructive" role="alert">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || !text.trim()} onClick={() => void submit()} data-testid="note-save">{busy ? "Saving…" : "Add note"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
