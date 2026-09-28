import { useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { firmError, updateMe } from "@/api/firm";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { usePerson } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { PersonAvatar } from "@/components/common/EntityLink";
import { Action, EmptyState, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { initials, useApp } from "@/context/AppContext";

export function PersonDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const person = usePerson(id);
  const { me } = useApp();
  const [editing, setEditing] = useState(false);

  return (
    <QueryState query={person} loading={<p className="text-sm text-muted-foreground">Loading…</p>}>
      {({ person: p, matters }) => (
        <div className="space-y-10">
          <PageHeader eyebrow={p.role} title={p.name} subtitle={[p.practice_areas.join(", "), p.office].filter(Boolean).join(" · ")}
            actions={me?.member_id === p.member_id ? (
              <Action icon="edit" onClick={() => setEditing(true)} testId="person-edit-me">Edit my expertise</Action>
            ) : undefined}>
            <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
              <PersonAvatar person={{ name: p.name, initials: initials(p.name) }} size={44} />
              {p.joined_year && <span>Joined {p.joined_year}</span>}
              {p.specializations.length > 0 && <span>{p.specializations.join(" · ")}</span>}
            </div>
          </PageHeader>

          <section>
            <SectionLabel>Matters you can see</SectionLabel>
            <DataTable
              testId="person-matters"
              getRowKey={(m) => m.matter_id}
              onRowClick={(m) => navigate(`/matters/${m.matter_id}`)}
              rows={matters}
              empty={<EmptyState title="No matters in your scope" description="This person's matters are either none or outside your access scope." />}
              columns={[
                {
                  key: "matter",
                  header: "Matter",
                  render: (m) => (
                    <div>
                      <div className="font-mono-id text-xs text-muted-foreground">{m.matter_code}</div>
                      <div>{m.title}</div>
                    </div>
                  ),
                },
                { key: "role", header: "Role", render: (m) => m.role_on_matter },
                { key: "status", header: "Status", align: "right", render: (m) => <StatusLabel status={m.status || "Open"} /> },
              ]}
            />
          </section>
          {editing && (
            <ExpertiseDialog practiceAreas={p.practice_areas} specializations={p.specializations} personId={p.member_id}
              onClose={() => setEditing(false)} />
          )}
        </div>
      )}
    </QueryState>
  );
}

const split = (text: string) => text.split(/[,\n]/).map((s) => s.trim()).filter(Boolean);

/** Your own practice areas and specialisations — what Ask the Firm finds you by. */
function ExpertiseDialog({ practiceAreas, specializations, personId, onClose }: {
  practiceAreas: string[]; specializations: string[]; personId: string; onClose: () => void;
}) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [areas, setAreas] = useState(practiceAreas.join(", "));
  const [specs, setSpecs] = useState(specializations.join(", "));
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateMe({ practice_areas: split(areas), specializations: split(specs) });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "person", personId] });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "people"] });
      toast("Profile updated");
      onClose();
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="expertise-dialog">
        <DialogHeader>
          <DialogTitle>Your expertise</DialogTitle>
          <DialogDescription>Colleagues find you by these in Ask the Firm and People.</DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <label className="block">
            <span className="text-xs text-muted-foreground">Practice areas (comma separated)</span>
            <input className="w-full rounded-md border border-border bg-card px-3 py-2" value={areas} onChange={(e) => setAreas(e.target.value)}
              data-testid="expertise-areas" />
          </label>
          <label className="block">
            <span className="text-xs text-muted-foreground">Specialisations (comma separated)</span>
            <textarea className="min-h-20 w-full rounded-md border border-border bg-card px-3 py-2" value={specs} onChange={(e) => setSpecs(e.target.value)} />
          </label>
          {error && <p className="text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy} onClick={() => void save()} data-testid="expertise-save">Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
