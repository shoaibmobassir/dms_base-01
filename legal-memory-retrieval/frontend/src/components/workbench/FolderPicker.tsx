import { useState } from "react";
import { useWorkspaceItems, type WorkspaceKind } from "@/api/workspaces";
import { Icon } from "@/components/common/primitives";
import { fieldControl } from "@/components/common/Field";
import { cn } from "@/lib/utils";

/**
 * Choose a folder of a workspace by clicking through its folders (no typed paths, so a typo never makes a new
 * folder by accident). "New folder here" names one inside the chosen folder; it is created when the action runs.
 */
export function FolderPicker({ kind, id, value, onChange, label = "Folder" }: {
  kind: WorkspaceKind;
  id: string;
  value: string;
  onChange: (path: string) => void;
  label?: string;
}) {
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");
  return (
    <div className="space-y-1.5" data-testid="folder-picker">
      <div className="flex items-center justify-between text-sm font-medium">
        <span>{label}</span>
        <span className="truncate pl-2 text-xs font-normal text-muted-foreground" data-testid="folder-picker-value">
          {value ? value.split("/").join(" / ") : "Top level"}
        </span>
      </div>
      <div className="max-h-48 overflow-y-auto rounded-md border border-border py-1" role="tree" aria-label={label}>
        <FolderRow path="" name="Top level" depth={0} selected={value === ""} onSelect={() => onChange("")} expandable={false} />
        {id ? <Level kind={kind} id={id} folder="" depth={1} value={value} onChange={onChange} /> : null}
      </div>
      {naming ? (
        <form
          className="flex gap-2"
          onSubmit={(e) => {
            e.preventDefault();
            const clean = name.trim().replace(/\//g, "-");
            if (!clean) return;
            onChange(value ? `${value}/${clean}` : clean);
            setNaming(false);
            setName("");
          }}
        >
          <input autoFocus value={name} onChange={(e) => setName(e.target.value)} maxLength={120} placeholder="New folder name"
            aria-label="New folder name" className={fieldControl} data-testid="folder-picker-new-name" />
          <button type="submit" className="rounded-md border border-border px-3 text-sm hover:bg-secondary">Use</button>
        </form>
      ) : (
        <button type="button" onClick={() => setNaming(true)} className="flex items-center gap-1 text-xs font-medium text-wine hover:underline"
          data-testid="folder-picker-new">
          <Icon name="create_new_folder" style={{ fontSize: 15 }} /> New folder {value ? `inside ${value.split("/").pop()}` : "here"}
        </button>
      )}
    </div>
  );
}

function Level({ kind, id, folder, depth, value, onChange }: {
  kind: WorkspaceKind; id: string; folder: string; depth: number; value: string; onChange: (p: string) => void;
}) {
  const items = useWorkspaceItems(kind, id, { folder, limit: 1 });
  const folders = items.data?.folders ?? [];
  // A folder named in this picker but not created yet shows under its parent until the action runs.
  const pending = value && value.startsWith(folder ? `${folder}/` : "") && value.slice(folder ? folder.length + 1 : 0).split("/").length === 1
    && !folders.some((f) => f.path === value) ? value : null;
  return (
    <>
      {folders.map((f) => <Node key={f.path} kind={kind} id={id} path={f.path} name={f.name} depth={depth} value={value} onChange={onChange} />)}
      {pending && <FolderRow path={pending} name={`${pending.split("/").pop()} (new)`} depth={depth} selected onSelect={() => undefined} expandable={false} />}
    </>
  );
}

function Node({ kind, id, path, name, depth, value, onChange }: {
  kind: WorkspaceKind; id: string; path: string; name: string; depth: number; value: string; onChange: (p: string) => void;
}) {
  const [open, setOpen] = useState(value.startsWith(`${path}/`));
  return (
    <>
      <FolderRow path={path} name={name} depth={depth} selected={value === path} open={open}
        onSelect={() => onChange(path)} onToggle={() => setOpen((o) => !o)} expandable />
      {open && <Level kind={kind} id={id} folder={path} depth={depth + 1} value={value} onChange={onChange} />}
    </>
  );
}

function FolderRow({ path, name, depth, selected, open, onSelect, onToggle, expandable }: {
  path: string; name: string; depth: number; selected: boolean; open?: boolean; onSelect: () => void; onToggle?: () => void; expandable: boolean;
}) {
  return (
    <div className={cn("flex items-center gap-1 pr-2 text-sm", selected ? "bg-wine-soft text-wine" : "hover:bg-secondary/60")}
      style={{ paddingLeft: 6 + depth * 14 }} role="treeitem" aria-selected={selected} aria-expanded={expandable ? !!open : undefined}>
      {expandable ? (
        <button type="button" aria-label={open ? `Collapse ${name}` : `Expand ${name}`} onClick={onToggle} className="rounded p-0.5 text-muted-foreground hover:bg-secondary">
          <Icon name={open ? "expand_more" : "chevron_right"} style={{ fontSize: 16 }} />
        </button>
      ) : <span className="w-5" />}
      <button type="button" onClick={onSelect} className="flex min-w-0 flex-1 items-center gap-1.5 py-1 text-left" data-testid="folder-picker-option" data-path={path}>
        <Icon name={path ? "folder" : "home_storage"} className="shrink-0 text-muted-foreground" style={{ fontSize: 16 }} />
        <span className="truncate">{name}</span>
      </button>
    </div>
  );
}
