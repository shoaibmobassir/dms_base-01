import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import { firmError } from "@/api/firm";
import {
  createProject,
  removeProjectMember,
  setProjectMember,
  updateProject,
  workspaceHref,
  type ProjectDetail,
  type ProjectMember,
} from "@/api/workspaces";
import { Field, fieldControl } from "@/components/common/Field";
import { MatterPicker } from "@/components/common/MatterPicker";
import { PersonPicker } from "@/components/common/PersonPicker";
import { Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";

/** Anyone can start a project: a workspace of their own for documents, sheets and notes, with the people they add. */
export function NewProjectDialog({ open, onOpenChange }: { open: boolean; onOpenChange: (open: boolean) => void }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [matterId, setMatterId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      const p = await createProject({ title: title.trim(), description: description.trim() || undefined, matter_id: matterId });
      await queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes("projects") });
      toast("Project created");
      onOpenChange(false);
      setTitle("");
      setDescription("");
      setMatterId(null);
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
          <DialogDescription>
            A workspace for any piece of work. Documents you add from a matter keep that matter's access: people in the
            project who are not on the matter will not see them.
          </DialogDescription>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (title.trim()) void submit();
          }}
        >
          <Field label="Name" error={error}>
            {(p) => (
              <input {...p} autoFocus value={title} onChange={(e) => setTitle(e.target.value)} maxLength={200}
                placeholder="e.g. Share purchase — due diligence" className={fieldControl} data-testid="project-title" />
            )}
          </Field>
          <Field label="What is it for?" hint="Optional">
            {(p) => (
              <textarea {...p} value={description} onChange={(e) => setDescription(e.target.value)} rows={3} maxLength={4000}
                className={fieldControl} data-testid="project-description" />
            )}
          </Field>
          <MatterPicker label="Related matter (optional)" value={matterId} onChange={(m) => setMatterId(m?.matter_id ?? null)}
            allowNone noneLabel="No matter" testId="project-matter" />
          <div className="flex justify-end gap-2 pt-1">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !title.trim()} data-testid="project-create">Create project</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

const ROLE_LABEL: Record<ProjectMember["role"], string> = { owner: "Owner", editor: "Editor", viewer: "Viewer" };
const ROLE_HINT: Record<ProjectMember["role"], string> = {
  owner: "Manages the project and its people",
  editor: "Adds, edits and files documents",
  viewer: "Reads the project's documents",
};

/** People in a project. Owners change roles and add or remove people; anyone can leave. */
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
  const { toast, me } = useApp();
  const memberId = me?.member_id ?? null;
  const [adding, setAdding] = useState<string | null>(null);
  const [role, setRole] = useState<ProjectMember["role"]>("editor");
  const [error, setError] = useState<string | null>(null);
  const canManage = project.my_level === "manage";
  const present = new Set(project.members.filter((m) => m.principal_type === "member").map((m) => m.principal_id));

  const refresh = () => queryClient.invalidateQueries({ predicate: (q) => q.queryKey.includes(project.project_id) || q.queryKey.includes("projects") });
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setError(null);
    try {
      await fn();
      await refresh();
      toast(done);
    } catch (err) {
      setError(firmError(err));
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="project-members-dialog">
        <DialogHeader>
          <DialogTitle>People in this project</DialogTitle>
          <DialogDescription>Project members see the project's own documents. Linked matter documents keep their matter's access.</DialogDescription>
        </DialogHeader>
        <ul className="divide-y divide-border rounded-md border border-border">
          {project.members.map((m) => (
            <li key={`${m.principal_type}:${m.principal_id}`} className="flex items-center gap-3 px-3 py-2.5 text-sm" data-testid="project-member">
              <Icon name={m.principal_type === "team" ? "groups" : "person"} className="text-muted-foreground" style={{ fontSize: 18 }} />
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{m.name ?? m.principal_id}</div>
                <div className="truncate text-xs text-muted-foreground">
                  {m.principal_type === "team" ? `Team of ${m.team_size ?? 0}` : m.title}
                </div>
              </div>
              {canManage ? (
                <select
                  aria-label={`Role of ${m.name ?? m.principal_id}`}
                  value={m.role}
                  onChange={(e) =>
                    run(() => setProjectMember(project.project_id, { principal_type: m.principal_type, principal_id: m.principal_id, role: e.target.value as ProjectMember["role"] }), "Role changed")
                  }
                  className="rounded-md border border-border bg-card px-2 py-1 text-xs"
                >
                  {(m.principal_type === "team" ? (["editor", "viewer"] as const) : (["owner", "editor", "viewer"] as const)).map((r) => (
                    <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                  ))}
                </select>
              ) : (
                <span className="text-xs text-muted-foreground">{ROLE_LABEL[m.role]}</span>
              )}
              {(canManage || m.principal_id === memberId) && (
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={m.principal_id === memberId ? "Leave project" : `Remove ${m.name ?? m.principal_id}`}
                  onClick={() => run(() => removeProjectMember(project.project_id, m.principal_type, m.principal_id), m.principal_id === memberId ? "You left the project" : "Removed")}
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
              <select value={role} onChange={(e) => setRole(e.target.value as ProjectMember["role"])} aria-label="Role"
                className="h-9 rounded-md border border-border bg-card px-2 text-sm">
                {(["editor", "viewer", "owner"] as const).map((r) => <option key={r} value={r}>{ROLE_LABEL[r]}</option>)}
              </select>
            </div>
            <p className="text-xs text-muted-foreground">{ROLE_HINT[role]}</p>
            <div className="flex justify-end">
              <Button size="sm" disabled={!adding} data-testid="project-add-confirm"
                onClick={() => adding && run(async () => { await setProjectMember(project.project_id, { principal_type: "member", principal_id: adding, role }); setAdding(null); }, "Added to the project")}>
                Add
              </Button>
            </div>
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
