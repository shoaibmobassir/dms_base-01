import { useEffect, useState, type ReactNode } from "react";
import { firmError } from "@/api/firm";
import {
  addTag,
  copyDocument,
  removeTag,
  useDocumentPlaces,
  useProjects,
  useWorkspaceItems,
  type DuplicateMatch,
  type WorkspaceDocument,
  type WorkspaceKind,
} from "@/api/workspaces";
import { Field, fieldControl } from "@/components/common/Field";
import { MatterPicker } from "@/components/common/MatterPicker";
import { Chip, Icon } from "@/components/common/primitives";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { cn } from "@/lib/utils";

export type TargetChoice = { kind: WorkspaceKind; id: string; folder: string; title?: string };

/**
 * Pick a workspace for a document: link it (show it there), copy it (a separate document), or file it into a
 * matter (the matter becomes its home). ``kinds`` limits the choices.
 */
export function TargetDialog({
  open,
  onOpenChange,
  title,
  description,
  confirm,
  kinds,
  exclude,
  askTitle,
  defaultTitle,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description?: ReactNode;
  confirm: string;
  kinds: WorkspaceKind[];
  /** The workspace the document is already in (not offered). */
  exclude?: { kind: WorkspaceKind; id: string };
  askTitle?: boolean;
  defaultTitle?: string;
  onConfirm: (choice: TargetChoice) => Promise<void>;
}) {
  const [kind, setKind] = useState<WorkspaceKind>(kinds[0]);
  const [projectId, setProjectId] = useState("");
  const [matterId, setMatterId] = useState<string | null>(null);
  const [folder, setFolder] = useState("");
  const [name, setName] = useState(defaultTitle ?? "");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const projects = useProjects();
  const editable = (projects.data ?? []).filter(
    (p) => p.my_role !== "viewer" && !(exclude?.kind === "project" && exclude.id === p.project_id),
  );

  useEffect(() => {
    if (open) {
      setKind(kinds[0]);
      setError(null);
      setFolder("");
      setName(defaultTitle ?? "");
    }
  }, [open, kinds, defaultTitle]);

  const id = kind === "project" ? projectId : kind === "matter" ? (matterId ?? "") : "me";
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm({ kind, id, folder: folder.trim(), title: askTitle ? name.trim() || undefined : undefined });
      onOpenChange(false);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  const label: Record<WorkspaceKind, string> = { project: "A project", matter: "A matter", library: "My library", firm: "Firm templates" };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-lg" data-testid="target-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          {description && <DialogDescription>{description}</DialogDescription>}
        </DialogHeader>
        <div className="space-y-4">
          {kinds.length > 1 && (
            <div className="flex gap-1 rounded-md border border-border p-0.5 text-sm" role="radiogroup" aria-label="Where">
              {kinds.map((k) => (
                <button
                  key={k}
                  type="button"
                  role="radio"
                  aria-checked={kind === k}
                  onClick={() => setKind(k)}
                  className={cn("flex-1 rounded px-3 py-1.5", kind === k ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}
                >
                  {label[k]}
                </button>
              ))}
            </div>
          )}
          {kind === "project" && (
            <Field label="Project" hint={editable.length ? undefined : "You are not an editor of any other project yet."}>
              {(p) => (
                <select {...p} value={projectId} onChange={(e) => setProjectId(e.target.value)} className={fieldControl} data-testid="target-project">
                  <option value="">Choose a project…</option>
                  {editable.map((pr) => (
                    <option key={pr.project_id} value={pr.project_id}>{pr.title}</option>
                  ))}
                </select>
              )}
            </Field>
          )}
          {kind === "matter" && (
            <MatterPicker label="Matter" value={matterId} onChange={(m) => setMatterId(m?.matter_id ?? null)} testId="target-matter" />
          )}
          <Field label="Folder" hint="Optional, e.g. Pleadings/Drafts">
            {(p) => <input {...p} value={folder} onChange={(e) => setFolder(e.target.value)} maxLength={500} className={fieldControl} data-testid="target-folder" />}
          </Field>
          {askTitle && (
            <Field label="Name of the copy">
              {(p) => <input {...p} value={name} onChange={(e) => setName(e.target.value)} maxLength={300} className={fieldControl} />}
            </Field>
          )}
          {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button disabled={busy || !id} onClick={submit} data-testid="target-confirm">{confirm}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/** Ask for one line of text (a folder name). */
export function PromptDialog({
  open,
  onOpenChange,
  title,
  label,
  initial = "",
  confirm,
  hint,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  label: string;
  initial?: string;
  confirm: string;
  hint?: string;
  onConfirm: (value: string) => Promise<void>;
}) {
  const [value, setValue] = useState(initial);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (open) {
      setValue(initial);
      setError(null);
    }
  }, [open, initial]);
  const submit = async () => {
    setBusy(true);
    setError(null);
    try {
      await onConfirm(value.trim());
      onOpenChange(false);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="prompt-dialog">
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
        </DialogHeader>
        <form
          className="space-y-4"
          onSubmit={(e) => {
            e.preventDefault();
            if (value.trim()) void submit();
          }}
        >
          <Field label={label} hint={hint} error={error}>
            {(p) => <input {...p} autoFocus value={value} onChange={(e) => setValue(e.target.value)} maxLength={500} className={fieldControl} data-testid="prompt-input" />}
          </Field>
          <div className="flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" disabled={busy || !value.trim()} data-testid="prompt-confirm">{confirm}</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

/** Tags on one document: where it lives (derived, read-only) and people's own tags. */
export function TagsDialog({
  documentId,
  open,
  onOpenChange,
  onChanged,
}: {
  documentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChanged?: () => void;
}) {
  const places = useDocumentPlaces(documentId, open);
  const [value, setValue] = useState("");
  const [error, setError] = useState<string | null>(null);
  const canEdit = places.data && places.data.my_level !== "read";
  const run = async (fn: () => Promise<unknown>) => {
    setError(null);
    try {
      await fn();
      await places.refetch();
      onChanged?.();
    } catch (err) {
      setError(firmError(err));
    }
  };
  const tags = places.data?.tags;
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-md" data-testid="tags-dialog">
        <DialogHeader>
          <DialogTitle>Tags</DialogTitle>
          <DialogDescription>Where the document lives is tagged automatically. Add your own tags to find it later.</DialogDescription>
        </DialogHeader>
        <div className="flex flex-wrap gap-1.5">
          {tags?.system.map((t) => (
            <Chip key={t.key} tone={t.home ? "wine" : "muted"}>
              {t.kind === "matter" || t.kind === "project" || t.kind === "library" ? (
                <Icon name={t.kind === "matter" ? "gavel" : t.kind === "project" ? "folder_special" : "person"} style={{ fontSize: 13 }} />
              ) : null}
              {t.label}
            </Chip>
          ))}
          {tags?.user.map((t) => (
            <Chip key={t} tone="accent">
              #{t}
              {canEdit && (
                <button type="button" aria-label={`Remove tag ${t}`} className="ml-1" onClick={() => run(() => removeTag(documentId, t))}>
                  <Icon name="close" style={{ fontSize: 12 }} />
                </button>
              )}
            </Chip>
          ))}
        </div>
        {canEdit && (
          <form
            className="flex gap-2"
            onSubmit={(e) => {
              e.preventDefault();
              if (value.trim()) void run(async () => { await addTag(documentId, value); setValue(""); });
            }}
          >
            <input value={value} onChange={(e) => setValue(e.target.value)} maxLength={60} placeholder="Add a tag"
              aria-label="New tag" className={fieldControl} data-testid="tag-input" />
            <Button type="submit" disabled={!value.trim()}>Add</Button>
          </form>
        )}
        {error && <p className="text-sm text-destructive" role="alert">{error}</p>}
      </DialogContent>
    </Dialog>
  );
}

export type DuplicateDecision = Record<string, "link" | "upload" | "skip">;

/**
 * Files that already exist as documents the person can read: use the existing document (link it here) or upload a
 * second, separate document. Files already in this workspace are skipped.
 */
export function DuplicatesDialog({
  open,
  files,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  files: { name: string; sha: string; matches: DuplicateMatch[] }[];
  onCancel: () => void;
  onConfirm: (decision: DuplicateDecision) => void;
}) {
  const [decision, setDecision] = useState<DuplicateDecision>({});
  useEffect(() => {
    if (open) {
      setDecision(Object.fromEntries(files.map((f) => [f.sha, f.matches.some((m) => m.already_here) ? "skip" : "link"])));
    }
  }, [open, files]);
  return (
    <Dialog open={open} onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="max-w-xl" data-testid="duplicates-dialog">
        <DialogHeader>
          <DialogTitle>Some files are already here</DialogTitle>
          <DialogDescription>
            These files already exist as documents you can open. Using the existing document keeps one copy and one
            history; uploading again makes a separate document.
          </DialogDescription>
        </DialogHeader>
        <ul className="max-h-[50vh] divide-y divide-border overflow-y-auto rounded-md border border-border">
          {files.map((f) => {
            const here = f.matches.find((m) => m.already_here);
            const first = f.matches[0];
            return (
              <li key={f.sha} className="space-y-1.5 px-3 py-2.5 text-sm">
                <div className="font-medium">{f.name}</div>
                {here ? (
                  <p className="text-xs text-muted-foreground">Already in this workspace as “{here.title}”. It will be skipped.</p>
                ) : (
                  <>
                    <p className="text-xs text-muted-foreground">
                      Same file as “{first.title}” in {first.home.label}.
                    </p>
                    <div className="flex gap-3 text-xs">
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name={f.sha} checked={decision[f.sha] === "link"} onChange={() => setDecision((d) => ({ ...d, [f.sha]: "link" }))} />
                        Use the existing document
                      </label>
                      <label className="flex items-center gap-1.5">
                        <input type="radio" name={f.sha} checked={decision[f.sha] === "upload"} onChange={() => setDecision((d) => ({ ...d, [f.sha]: "upload" }))} />
                        Upload as a separate document
                      </label>
                    </div>
                  </>
                )}
              </li>
            );
          })}
        </ul>
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={onCancel}>Cancel</Button>
          <Button onClick={() => onConfirm(decision)} data-testid="duplicates-confirm">Continue</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

/**
 * Start a document from one of the firm's templates: the template is copied into this workspace as a new document
 * (its own history, linked to the template it came from); the template itself is never edited.
 */
export function NewFromTemplateDialog({ kind, id, open, onOpenChange, onCreated, canFill }: {
  kind: WorkspaceKind; id: string; open: boolean; onOpenChange: (o: boolean) => void
  onCreated: (doc: { document_id: string; title: string }, fill: boolean) => void
  /** Offer to hand the new document to the Assistant to fill in. */
  canFill?: boolean
}) {
  const [fill, setFill] = useState(true);
  const items = useWorkspaceItems("firm", "templates", { recursive: true, enabled: open });
  const [chosen, setChosen] = useState<WorkspaceDocument | null>(null);
  const [name, setName] = useState("");
  const [folder, setFolder] = useState("");
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => { if (open) { setChosen(null); setName(""); setError(null); } }, [open]);
  const docs = (items.data?.documents ?? []).filter((d): d is WorkspaceDocument => !d.restricted)
    .filter((d) => !q || d.title.toLowerCase().includes(q.toLowerCase()) || d.folder.toLowerCase().includes(q.toLowerCase()));
  const create = async () => {
    if (!chosen) return;
    setBusy(true);
    setError(null);
    try {
      const made = await copyDocument(chosen.document_id, { kind, id, folder: folder.trim(), title: name.trim() || chosen.title });
      onOpenChange(false);
      onCreated(made, canFill === true && fill);
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-xl" data-testid="new-from-template-dialog">
        <DialogHeader>
          <DialogTitle>New from template</DialogTitle>
          <DialogDescription>Pick one of the firm's templates. You get your own copy here; the template stays as it is.</DialogDescription>
        </DialogHeader>
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Find a template" aria-label="Find a template" className={fieldControl} />
        <ul className="max-h-60 divide-y divide-border overflow-y-auto rounded-md border border-border" data-testid="template-list">
          {items.isPending && <li className="px-3 py-2 text-xs text-muted-foreground">Loading…</li>}
          {!items.isPending && docs.length === 0 && (
            <li className="px-3 py-2 text-xs text-muted-foreground">No templates yet. People who curate the firm's library add them under Templates.</li>
          )}
          {docs.map((d) => (
            <li key={d.document_id}>
              <button type="button" onClick={() => { setChosen(d); setName(d.title); }}
                className={cn("flex w-full items-center gap-2 px-3 py-1.5 text-left text-sm hover:bg-secondary/60", chosen?.document_id === d.document_id && "bg-wine-soft text-wine")}
                data-testid="template-option">
                <Icon name="description" style={{ fontSize: 15 }} className="text-muted-foreground" />
                <span className="truncate">{d.title}</span>
                {d.folder && <span className="ml-auto truncate pl-2 text-xs text-muted-foreground">{d.folder}</span>}
              </button>
            </li>
          ))}
        </ul>
        {chosen && (
          <div className="grid grid-cols-2 gap-3">
            <Field label="Name of the new document" error={error}>
              {(p) => <input {...p} value={name} onChange={(e) => setName(e.target.value)} maxLength={300} className={fieldControl} data-testid="template-name" />}
            </Field>
            <Field label="Folder" hint="Optional">
              {(p) => <input {...p} value={folder} onChange={(e) => setFolder(e.target.value)} maxLength={500} className={fieldControl} />}
            </Field>
          </div>
        )}
        {canFill && chosen && (
          <label className="flex items-center gap-2 text-sm">
            <input type="checkbox" checked={fill} onChange={(e) => setFill(e.target.checked)} data-testid="template-fill" />
            Then ask the Assistant to fill in the blanks (it asks you for what it needs)
          </label>
        )}
        <div className="flex justify-end gap-2">
          <Button variant="outline" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button disabled={!chosen || busy} onClick={create} data-testid="template-create">Create document</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
