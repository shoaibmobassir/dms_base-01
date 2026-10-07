import { useState } from "react";
import { Link } from "react-router-dom";
import { useProjects, workspaceHref, type ProjectSummary } from "@/api/workspaces";
import { QueryState } from "@/components/common/QueryState";
import { Chip, EmptyState, Icon, MonoId, PageHeader, SearchField } from "@/components/common/primitives";
import { NewProjectDialog } from "@/components/workbench/ProjectDialogs";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { usePageTitle } from "@/lib/use-page-title";
import { cn } from "@/lib/utils";

/** Projects: workspaces anyone can start, with their own people. Matters stay the firm's organised record. */
export function ProjectsPage() {
  usePageTitle("Projects");
  const [q, setQ] = useState("");
  const [archived, setArchived] = useState(false);
  const [creating, setCreating] = useState(false);
  const query = useDebounced(q, 250);
  const projects = useProjects({ q: query, archived });

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Projects"
        count={projects.data ? `${projects.data.length} ${projects.data.length === 1 ? "project" : "projects"}` : undefined}
        subtitle="Workspaces for any piece of work. Documents are stored once: add a matter's document to a project and it stays the same document, with the matter's access."
        actions={
          <Button onClick={() => setCreating(true)} data-testid="new-project">
            <Icon name="add" style={{ fontSize: 18 }} /> New project
          </Button>
        }
      />
      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[240px] flex-1">
          <SearchField value={q} onChange={setQ} placeholder="Find a project" testId="projects-search" />
        </div>
        <div className="flex rounded-md border border-border p-0.5 text-sm" role="tablist" aria-label="Show">
          {([false, true] as const).map((a) => (
            <button
              key={String(a)}
              role="tab"
              aria-selected={archived === a}
              onClick={() => setArchived(a)}
              className={cn("rounded px-3 py-1", archived === a ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}
            >
              {a ? "Archived" : "Active"}
            </button>
          ))}
        </div>
      </div>
      <QueryState
        query={projects}
        isEmpty={(d) => d.length === 0}
        empty={
          <EmptyState
            icon="folder_special"
            title={q ? "No projects match" : archived ? "No archived projects" : "No projects yet"}
            description={
              q || archived
                ? undefined
                : "Start a project for due diligence, a pitch, research or anything that is not a matter. Add people, upload files or bring in documents from your matters."
            }
            action={!q && !archived ? <Button onClick={() => setCreating(true)}>New project</Button> : undefined}
          />
        }
      >
        {(items) => (
          <ul className="divide-y divide-border border-y border-border" data-testid="projects-list">
            {items.map((p) => <ProjectRow key={p.project_id} p={p} />)}
          </ul>
        )}
      </QueryState>
      <NewProjectDialog open={creating} onOpenChange={setCreating} />
    </div>
  );
}

function ProjectRow({ p }: { p: ProjectSummary }) {
  return (
    <li>
      <Link
        to={workspaceHref("project", p.project_id)}
        className="group flex items-start gap-4 px-2 py-4 transition-colors hover:bg-secondary/60"
        data-testid="project-row"
      >
        <Icon name="folder_special" className="mt-0.5 text-muted-foreground group-hover:text-wine" style={{ fontSize: 22 }} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-foreground group-hover:text-wine">{p.title}</span>
            {p.my_role && p.my_role !== "owner" && <Chip>{p.my_role === "editor" ? "Editor" : "Viewer"}</Chip>}
            {p.matter && (
              <Chip tone="wine">
                <MonoId className="text-wine">{p.matter.matter_code}</MonoId>
              </Chip>
            )}
          </div>
          {p.description && <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">{p.description}</p>}
        </div>
        <div className="hidden shrink-0 text-right text-xs text-muted-foreground sm:block">
          <div>
            <span className="font-mono-id">{p.document_count}</span> {p.document_count === 1 ? "document" : "documents"} ·{" "}
            <span className="font-mono-id">{p.member_count}</span> {p.member_count === 1 ? "person" : "people"}
          </div>
          <div className="mt-0.5">Updated {formatDate(p.updated_at)}</div>
        </div>
      </Link>
    </li>
  );
}
