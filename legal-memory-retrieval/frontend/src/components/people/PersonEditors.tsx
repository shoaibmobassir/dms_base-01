import { useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { deactivatePerson, firmError, reactivatePerson, updatePerson } from "@/api/firm";
import type { Person } from "@/api/types";
import { Field, fieldControl } from "@/components/common/Field";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";

const list = (text: string) => text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

export function usePersonWrite(personId: string) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      for (const k of ["person", "people", "admin-users"]) await queryClient.invalidateQueries({ queryKey: [identityKey, k] });
      toast(done);
      return true;
    } catch (err) {
      setError(firmError(err));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error, personId };
}

/** An administrator edits someone's profile: title, office, email, what they practise. */
export function EditPersonDialog({ person, onClose }: { person: Person; onClose: () => void }) {
  const { run, busy, error } = usePersonWrite(person.member_id);
  const [name, setName] = useState(person.name);
  const [role, setRole] = useState(person.role);
  const [office, setOffice] = useState(person.office ?? "");
  const [email, setEmail] = useState(person.email ?? "");
  const [areas, setAreas] = useState(person.practice_areas.join(", "));
  const [specs, setSpecs] = useState(person.specializations.join(", "));
  const submit = async () => {
    const body = { name: name.trim(), role: role.trim(), office, email, practice_areas: list(areas), specializations: list(specs) };
    if (await run(() => updatePerson(person.member_id, body), "Profile updated")) onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="edit-person-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Edit {person.name}</DialogTitle>
          <DialogDescription>Changes are recorded in the audit trail.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name">{(f) => <input {...f} className={fieldControl} value={name} onChange={(e) => setName(e.target.value)} data-testid="edit-person-name" />}</Field>
            <Field label="Title">{(f) => <input {...f} className={fieldControl} value={role} onChange={(e) => setRole(e.target.value)} />}</Field>
            <Field label="Office">{(f) => <input {...f} className={fieldControl} value={office} onChange={(e) => setOffice(e.target.value)} />}</Field>
            <Field label="Email">{(f) => <input {...f} type="email" className={fieldControl} value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
          </div>
          <Field label="Practice areas" hint="Separate with commas.">{(f) => <input {...f} className={fieldControl} value={areas} onChange={(e) => setAreas(e.target.value)} />}</Field>
          <Field label="Specialisations" hint="Separate with commas.">{(f) => <textarea {...f} className={`${fieldControl} min-h-16`} value={specs} onChange={(e) => setSpecs(e.target.value)} />}</Field>
          {error && <p className="text-destructive" role="alert" data-testid="form-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || !name.trim()} onClick={() => void submit()} data-testid="edit-person-save">{busy ? "Saving…" : "Save"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Someone has left or is away: they can no longer sign in or be staffed, and their history stays. */
export function DeactivatePersonDialog({ person, onClose }: { person: Person; onClose: () => void }) {
  const { run, busy, error } = usePersonWrite(person.member_id);
  const [reason, setReason] = useState("");
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="deactivate-person-dialog">
        <DialogHeader>
          <DialogTitle className="font-display text-2xl">Deactivate {person.name}?</DialogTitle>
          <DialogDescription>
            They can no longer sign in, their keys stop working and they cannot be staffed on matters. Their past work and history stay. You can reactivate them.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <Field label="Why" hint="Recorded in the audit trail. Required.">
            {(f) => <textarea {...f} className={`${fieldControl} min-h-16`} value={reason} onChange={(e) => setReason(e.target.value)} data-testid="deactivate-reason" />}
          </Field>
          {error && <p className="text-destructive" role="alert" data-testid="form-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button
              variant="destructive"
              disabled={busy || !reason.trim()}
              onClick={() => void run(() => deactivatePerson(person.member_id, reason.trim()), `${person.name} deactivated`).then((ok) => ok && onClose())}
              data-testid="deactivate-confirm"
            >
              {busy ? "Working…" : "Deactivate"}
            </Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function useReactivate(person: Person) {
  const { run, busy } = usePersonWrite(person.member_id);
  return { busy, reactivate: () => run(() => reactivatePerson(person.member_id), `${person.name} reactivated`) };
}
