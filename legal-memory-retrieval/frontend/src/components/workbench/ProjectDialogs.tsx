import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import { useTeams } from "@/api/access";
import {
  createProject,
  removeProjectMember,
  setProjectMember,
  updateProject,
  useProjects,
  workspaceHref,
  type ProjectDetail,
  type ProjectMember,
} from "@/api/workspaces";
import { useConfirm } from "@/components/common/Confirm";
import { Field, fieldControl } from "@/components/common/Field";
import { MatterPicker } from "@/components/common/MatterPicker";
import { PersonPicker } from "@/components/common/PersonPicker";
import { SearchPicker } from "@/components/common/SearchPicker";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";

type Role = ProjectMember["role"];
type Invite = { type: "member" | "team"; id: string; name: string; role: Role };

/** Anyone can start a project: a shared working folder for documents and reviews, with the people they add. */
export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [matterId, setMatterId] = useState<string | null>(null);
  const [invites, setInvites] = useState<Invite[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const mine = useProjects();
  const clash = title.trim() && (mine.data ?? []).some((p) => p.title.trim().toLowerCase() === title.trim().toLowerCase());

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await createProject({ title: title.trim(), description: description.trim() || undefined, matter_id: matterId });
      const failed: string[] = [];
      for (const inv of invites) {
        await setProjectMember(p.project_id, { principal_type: inv.type, principal_id: inv.id, role: inv.role }).catch(() => failed.push(inv.name));
      }
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("projects") });
      toast(failed.length ? `Project created; could not add ${failed.join(", ")}` : "Project created");
      onOpenChange(false);
      setTitle("");
      setDescription("");
      setMatterId(null);
      setInvites([]);
      navigate(workspaceHref("project", p.project_id));
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="new-project-dialog">
        <DialogHeader>
          <DialogTitle>New project</DialogTitle>
          <DialogDescription>A shared working folder. Only the people you add can open it.</DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) void submit();
          }}
        >
          <Field label="Name" error={error} hint={clash ? "You already have a project with this name." : undefined}>
            {(p) => (
              <input {...p} autoFocus value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200}
                placeholder="e.g. Share purchase — due diligence" className={fieldControl} data-testid="project-title" />
            )}
          </Field>
          <Field label="What is it for?" hint="Optional">
            {(p) => (
              <textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} rows={2} maxLength={4000}
                className={fieldControl} data-testid="project-description" />
            )}
          </Field>
          <MatterPicker label="Related matter (optional)" value={matterId} onChange={(m) => setMatterId(m?.matter_id ?? null)}
            allowNone noneLabel="No matter" testId="project-matter" />
          <AddPeople invites={invites} onChange={setInvites} />
          {matterId && invites.length > 0 && (
            <p className="text-xs text-muted-foreground">Documents you add from the matter stay hidden from people who are not on the matter.</p>
          )}
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !title.trim()} data-testid="project-create">Create project</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Pick people and teams to add, each with a role (used when creating a project). */
function AddPeople({ invites, onChange }: { invites: Invite[]; onChange: (i: Invite[]) => void }) {
  const [person, setPerson] = useState<string | null>(null);
  const teams = useTeams();
  const present = new Set(invites.filter((i) => i.type === "member").map((i) => i.id));
  return (
    <div className="space-y-2">
      <div className="text-sm font-medium">People <span className="font-normal text-muted-foreground">(optional; you can add them later)</span></div>
      {invites.length > 0 && (
        <ul className="divide-y divide-border rounded-md border border-border">
          {invites.map((i) => (
            <li key={`${i.type}:${i.id}`} className="flex items-center gap-2 px-3 py-1.5 text-sm">
              <Icon name={i.type === "team" ? "groups" : "person"} className="text-muted-foreground" style={{ fontSize: 16 }} />
              <span className="min-w-0 flex-1 truncate">{i.name}</span>
              <RoleSelect value={i.role} team={i.type === "team"} onChange={(role) => onChange(invites.map((x) => (x === i ? { ...x, role } : x)))} label={`Role of ${i.name}`} />
              <button type="button" aria-label={`Do not add ${i.name}`} onClick={() => onChange(invites.filter((x) => x !== i))} className="rounded p-0.5 text-muted-foreground hover:bg-secondary">
                <Icon name="close" style={{ fontSize: 15 }} />
              </button>
            </li>
          ))}
        </ul>
      )}
      <div className="grid grid-cols-2 gap-2">
        <PersonPicker value={person} exclude={present} label="Add a person" testId="new-project-person"
          onChange={(id, p?: { name?: string }) => {
            if (!id) return setPerson(null);
            onChange([...invites, { type: "member", id, name: p?.name ?? id, role: "editor" }]);
            setPerson(null);
          }} />
        <SearchPicker
          label="Add a team"
          selectedId={null}
          selectedLabel={null}
          onSelect={(o) => o && !invites.some((i) => i.type === "team" && i.id === o.id) && onChange([...invites, { type: "team", id: o.id, name: o.title, role: "viewer" }])}
          useOptions={(q) => ({
            options: (teams.data ?? []).filter((t) => !q || t.name.toLowerCase().includes(q.toLowerCase()))
              .map((t) => ({ id: t.team_id, title: t.name, subtitle: `${t.member_count} people` })),
            isPending: teams.isPending,
          })}
          placeholder="Find a team"
          testId="new-project-team"
        />
      </div>
    </div>
  );
}

const ROLE_LABEL: Record<Role, string> = { owner: "Owner", editor: "Editor", viewer: "Viewer" };
const ROLE_HINT: Record<Role, string> = {
  owner: "Manages the project and its people",
  editor: "Adds, edits and files documents",
  viewer: "Reads the project's documents",
};

function RoleSelect({ value, onChange, team, label }: { value: Role; onChange: (r: Role) => void; team?: boolean; label: string }) {
  return (
    <select aria-label={label} value={value} onChange={(e) => onChange(e.target.value as Role)}
      className="rounded-md border border-border bg-card px-2 py-1 text-xs" title={ROLE_HINT[value]}>
      {(team ? (["editor", "viewer"] as const) : (["owner", "editor", "viewer"] as const)).map((r) => (
        <option key={r} value={r}>{ROLE_LABEL[r]}</option>
      ))}
    </select>
  );
}

/** People in a project. Owners change roles and add or remove people or teams; anyone can leave. */
export function ProjectMembersDialog({
  project,
  open,
  onOpenChange,
}: {
  project: ProjectDetail;
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  const queryClient = useQueryClient();
  const navigate = useNavigate();
  const confirm = useConfirm();
  const { toast, me } = useApp();
  const memberId = me?.member_id ?? null;
  const teams = useTeams();
  const [adding, setAdding] = useState<string | null>(null);
  const [role, setRole] = useState<Role>("editor");
  const [error, setError] = useState<string | null>(null);
  const canManage = project.my_level === "manage";
  const present = new Set(project.members.filter((m) => m.principal_type === "member").map((m) => m.principal_id));
  const owners = project.members.filter((m) => m.role === "owner" && m.principal_type === "member").length;

  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(project.project_id) || q.queryKey.includes("projects") });
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null);
    try {
      await fn();
      await refresh();
      toast(done);
      return true;
    } catch (err) {
      setError(firmError(err));
      return false;
    }
  };
  const changeRole = async (m: ProjectMember, next: Role) => {
    const self = m.principal_id === memberId;
    if (self && m.role === "owner" && next !== "owner") {
      const ok = await confirm({
        title: "Give up owning this project?",
        description: owners > 1 ? "You will no longer be able to manage its people, details or archive it." : "You are its only owner; make someone else an owner first.",
        confirmLabel: "Change my role",
      });
      if (!ok) return;
    }
    await run(() => setProjectMember(project.project_id, { principal_type: m.principal_type, principal_id: m.principal_id, role: next }), "Role changed");
  };
  const remove = async (m: ProjectMember) => {
    const self = m.principal_id === memberId;
    const ok = await confirm({
      title: self ? "Leave this project?" : `Remove ${m.name ?? m.principal_id}?`,
      description: self
        ? "You will lose access to its own documents and reviews. An owner can add you again."
        : "They lose access to the project's own documents and reviews. Documents they added stay.",
      confirmLabel: self ? "Leave project" : "Remove",
      destructive: true,
    });
    if (!ok) return;
    const done = await run(() => removeProjectMember(project.project_id, m.principal_type, m.principal_id), self ? "You left the project" : "Removed");
    if (done && self) navigate("/projects");
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="project-members-dialog">
        <DialogHeader>
          <DialogTitle>People in this project</DialogTitle>
          <DialogDescription>They see the project's own documents. Documents shown here from a matter keep the matter's access.</DialogDescription>
        </DialogHeader>
        <ul className="divide-y divide-border rounded-md border border-border">
          {project.members.map((m) => (
            <li key={`${m.principal_type}:${m.principal_id}`} className="flex items-center gap-3 px-3 py-2.5 text-sm" data-testid="project-member">
              <Icon name={m.principal_type === "team" ? "groups" : "person"} className="text-muted-foreground" style={{ fontSize: 18 }} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{m.name ?? m.principal_id}{m.principal_id === memberId ? " (you)" : ""}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {m.principal_type === "team" ? `Team of ${m.team_size ?? 0}` : m.title}
                </div>
              </div>
              {canManage ? (
                <RoleSelect value={m.role} team={m.principal_type === "team"} label={`Role of ${m.name ?? m.principal_id}`} onChange={(r) => void changeRole(m, r)} />
              ) : (
                <span className="text-xs text-muted-foreground">{ROLE_LABEL[m.role]}</span>
              )}
              {(canManage || m.principal_id === memberId) && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={m.principal_id === memberId ? "Leave project" : `Remove ${m.name ?? m.principal_id}`}
                  onClick={() => void remove(m)}
                >
                  {m.principal_id === memberId ? "Leave" : <Icon name="close" style={{ fontSize: 16 }} />}
                </Button>
              )}
            </li>
          ))}
        </ul>
        {canManage && (
          <div className="space-y-2 rounded-md bg-secondary/50 p-3">
            <div className="grid grid-cols-[1fr_auto] items-end gap-2">
              <PersonPicker value={adding} onChange={setAdding} exclude={present} label="Add a person" testId="project-add-person" />
              <select value={role} onChange={(e) => setRole(e.target.value as Role)} aria-label="Role"
                className="h-9 rounded-md border border-border bg-card px-2 text-sm">
                {(["editor", "viewer", "owner"] as const).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </div>
            <p className="text-xs text-muted-foreground">{ROLE_HINT[role]}</p>
            <div className="flex justify-end">
              <Button size="sm" disabled={!adding} data-testid="project-add-confirm"
                onClick={() => adding && void run(async () => { await setProjectMember(project.project_id, { principal_type: "member", principal_id: adding, role }); setAdding(null); }, "Added to the project")}>
                Add
              </Button>
            </div>
            <SearchPicker
              label="Or add a whole team (as viewers; change the role after)"
              selectedId={null}
              selectedLabel={null}
              onSelect={(o) => o && void run(() => setProjectMember(project.project_id, { principal_type: "team", principal_id: o.id, role: "viewer" }), `${o.title} added`)}
              useOptions={(q) => ({
                options: (teams.data ?? [])
                  .filter((t) => !project.members.some((m) => m.principal_type === "team" && m.principal_id === t.team_id))
                  .filter((t) => !q || t.name.toLowerCase().includes(q.toLowerCase()))
                  .map((t) => ({ id: t.team_id, title: t.name, subtitle: `${t.member_count} people` })),
                isPending: teams.isPending,
              })}
              placeholder="Find a team"
              testId="project-add-team"
            />
          </div>
        )}
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}

/** Rename a project or change its description and related matter (owners). */
export function EditProjectDialog({ project, open, onOpenChange }: { project: ProjectDetail; open: boolean; onOpenChange: (open: boolean) => void }) {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const [title, setTitle] = useState(project.title);
  const [description, setDescription] = useState(project.description ?? "");
  const [matterId, setMatterId] = useState<string | null>(project.matter?.matter_id ?? null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await updateProject(project.project_id, { title: title.trim(), description: description.trim() || null, matter_id: matterId, row_version: project.row_version });
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(project.project_id) || q.queryKey.includes("projects") });
      toast("Project updated");
      onOpenChange(false);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="edit-project-dialog">
        <DialogHeader>
          <DialogTitle>Project details</DialogTitle>
        </DialogHeader>
        <div className="space-y-4">
          <Field label="Name" error={error}>
            {(p) => <input {...p} value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200} className={fieldControl} />}
          </Field>
          <Field label="What is it for?">
            {(p) => <textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={4000} className={fieldControl} />}
          </Field>
          <MatterPicker label="Related matter" value={matterId} onChange={(m) => setMatterId(m?.matter_id ?? null)} allowNone noneLabel="No matter" />
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={busy || !title.trim()} onClick={submit}>Save</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
