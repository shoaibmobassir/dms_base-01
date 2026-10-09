import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useProjectList, workspaceHref, type ProjectScope, type ProjectSummary } from "@/api/workspaces";
import { Pager, QueryState } from "@/components/common/QueryState";
import { Chip, EmptyState, Icon, PageHeader, SearchField } from "@/components/common/primitives";
import { NewProjectDialog } from "@/components/workbench/ProjectDialogs";
import { Button } from "@/components/ui/button";
import { formatDate } from "@/lib/format";
import { useDebounced } from "@/lib/use-debounced";
import { usePageTitle } from "@/lib/use-page-title";
import { cn } from "@/lib/utils";

const SCOPES: { key: ProjectScope; label: string }[] = [
  { key: "all", label: "All" },
  { key: "mine", label: "Mine" },
  { key: "shared", label: "Shared with me" },
];

/** Projects: shared working folders for anything that is not a matter. Matters stay the firm's organised record. */
export function ProjectsPage() {
  usePageTitle("Projects");
  // Filters live in the address bar, so a reload or a shared link keeps them.
  const [params, setParams] = useSearchParams();
  const scope = (params.get("scope") as ProjectScope | null) ?? "all";
  const archived = params.get("archived") === "1";
  const sort = params.get("sort") === "title" ? "title" : "updated";
  const set = (key: string, value: string | null) =>
    setParams((prev) => {
      const next = new URLSearchParams(prev);
      if (value) next.set(key, value);
      else next.delete(key);
      next.delete("page");
      return next;
    }, { replace: true });
  const [q, setQ] = useState(params.get("q") ?? "");
  const query = useDebounced(q, 250);
  useEffect(() => set("q", query.trim() || null), [query]); // eslint-disable-line react-hooks/exhaustive-deps
  const page = Number(params.get("page") ?? 0) || 0;
  const [creating, setCreating] = useState(params.get("new") === "1");
  const projects = useProjectList({ q: query, archived, scope, sort, page });

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Projects"
        count={projects.data ? `${projects.data.total} ${projects.data.total === 1 ? "project" : "projects"}` : undefined}
        subtitle="Shared working folders for anything that is not a matter: due diligence, a pitch, research. Add people and documents; matter documents keep the matter's access."
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
        <Segmented
          label="Whose"
          value={scope}
          options={SCOPES}
          onChange={(v) => set("scope", v === "all" ? null : v)}
          testId="projects-scope"
        />
        <Segmented
          label="Show"
          value={archived ? "archived" : "active"}
          options={[{ key: "active", label: "Active" }, { key: "archived", label: "Archived" }]}
          onChange={(v) => set("archived", v === "archived" ? "1" : null)}
        />
        <select value={sort} onChange={(e) => set("sort", e.target.value === "title" ? "title" : null)} aria-label="Sort"
          className="rounded-md border border-border bg-card px-2.5 py-2 text-sm" data-testid="projects-sort">
          <option value="updated">Recently changed</option>
          <option value="title">Name</option>
        </select>
      </div>
      <QueryState
        query={projects}
        isEmpty={(d) => d.items.length === 0}
        empty={
          <EmptyState
            icon="folder_special"
            title={q ? "No projects match" : archived ? "No archived projects" : scope === "shared" ? "Nobody has added you to a project yet" : "No projects yet"}
            description={
              q || archived || scope === "shared"
                ? undefined
                : "Start a project for due diligence, a pitch, research or anything that is not a matter. Add people, upload files or bring in documents from your matters."
            }
            action={!q && !archived && scope !== "shared" ? <Button onClick={() => setCreating(true)}>New project</Button> : undefined}
          />
        }
      >
        {(d) => (
          <>
            <ul className="divide-y divide-border border-y border-border" data-testid="projects-list">
              {d.items.map((p) => <ProjectRow key={p.project_id} p={p} />)}
            </ul>
            <Pager page={page} total={d.total} pageSize={50} onPage={(n) => setParams((prev) => {
              const next = new URLSearchParams(prev);
              if (n) next.set("page", String(n));
              else next.delete("page");
              return next;
            })} />
          </>
        )}
      </QueryState>
      <NewProjectDialog open={creating} onOpenChange={(o) => { setCreating(o); if (!o && params.get("new")) set("new", null); }} />
    </div>
  );
}

function Segmented<K extends string>({ label, value, options, onChange, testId }: {
  label: string; value: K; options: { key: K; label: string }[]; onChange: (v: K) => void; testId?: string;
}) {
  return (
    <div className="flex rounded-md border border-border p-0.5 text-sm" role="radiogroup" aria-label={label} data-testid={testId}>
      {options.map((o) => (
        <button
          key={o.key}
          type="button"
          role="radio"
          aria-checked={value === o.key}
          onClick={() => onChange(o.key)}
          className={cn("rounded px-3 py-1", value === o.key ? "bg-secondary font-medium" : "text-muted-foreground hover:text-foreground")}
        >
          {o.label}
        </button>
      ))}
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
        <Icon name="folder_special" className="mt-0.5 shrink-0 text-muted-foreground group-hover:text-wine" style={{ fontSize: 22 }} />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className="truncate font-medium text-foreground group-hover:text-wine">{p.title}</span>
            {p.my_role && p.my_role !== "owner" && <Chip>{p.my_role === "editor" ? "You can edit" : "You can read"}</Chip>}
            {p.matter && (
              <Chip tone="wine">
                <Icon name="gavel" style={{ fontSize: 13 }} /> <span className="max-w-[260px] truncate">{p.matter.title}</span>
              </Chip>
            )}
          </div>
          {p.description && <p className="mt-0.5 line-clamp-1 text-sm text-muted-foreground">{p.description}</p>}
          <p className="mt-0.5 text-xs text-muted-foreground sm:hidden">
            {p.document_count} {p.document_count === 1 ? "document" : "documents"} · updated {formatDate(p.updated_at)}
          </p>
        </div>
        <div className="hidden shrink-0 text-right text-xs text-muted-foreground sm:block">
          <div>
            <span className="font-mono-id">{p.document_count}</span> {p.document_count === 1 ? "document" : "documents"} ·{" "}
            <span className="font-mono-id">{p.member_count}</span> {p.member_count === 1 ? "person" : "people"}
          </div>
          <div className="mt-0.5">{p.my_role === "owner" ? "Yours" : p.owner_name ? `Owner ${p.owner_name}` : ""} · updated {formatDate(p.updated_at)}</div>
        </div>
      </Link>
    </li>
  );
}
