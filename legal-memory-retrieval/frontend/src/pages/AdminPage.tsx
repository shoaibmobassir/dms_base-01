import { useState } from "react";
import { Link } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  can,
  createTeam,
  decideRequest,
  deleteTeam,
  setTeamMember,
  setUserRoles,
  useAccessRequests,
  useAdminUsers,
  useFirmRoles,
  useMyAccess,
  useTeams,
  useWalls,
  type AdminUser,
  type FirmRole,
} from "@/api/access";
import { usePeople } from "@/api/resources";
import { createPerson, fetchArchived, firmError, importFile, restoreDocument, type ImportEntity, type ImportReport } from "@/api/firm";
import { downloadFile } from "@/api/client";
import { DataTable } from "@/components/common/DataTable";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, MonoId, PageHeader, SectionLabel, StatusLabel, TableSkeleton } from "@/components/common/primitives";
import { useConfirm } from "@/components/common/Confirm";
import { Field } from "@/components/common/Field";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

type Section = "users" | "teams" | "walls" | "requests" | "import" | "archive";

const SECTIONS: { key: Section; label: string; permission: string[] }[] = [
  { key: "users", label: "Users & roles", permission: ["users.manage", "roles.manage", "walls.manage"] },
  { key: "teams", label: "Teams", permission: ["teams.manage"] },
  { key: "walls", label: "Ethical walls", permission: ["walls.manage", "audit.read"] },
  { key: "requests", label: "Access requests", permission: ["access_requests.decide", "walls.manage"] },
  { key: "import", label: "Import", permission: ["users.manage", "clients.create", "matters.create"] },
  { key: "archive", label: "Archive", permission: ["users.manage"] },
];

/** Firm administration: people and roles, teams, walls and access requests. */
export function AdminPage() {
  const me = useMyAccess();
  const visible = SECTIONS.filter((s) => s.permission.some((p) => can(me.data, p)));
  const [section, setSection] = useState<Section | null>(null);
  const active = section ?? visible[0]?.key ?? null;

  if (me.isPending) return <p className="text-sm text-muted-foreground">Loading…</p>;
  if (!visible.length || !active) {
    return <EmptyState icon="lock" title="Administration is limited to firm administrators and risk & compliance" />;
  }
  return (
    <div className="space-y-8" data-testid="admin-page">
      <PageHeader compact title="Administration" subtitle="People, roles, teams and who can see which matters. Every change is audited." />
      <div className="flex flex-wrap gap-1 border-b border-border">
        {visible.map((s) => (
          <button
            key={s.key}
            type="button"
            onClick={() => setSection(s.key)}
            data-testid={`admin-tab-${s.key}`}
            className={cn("relative px-3 py-2 text-sm", active === s.key ? "font-semibold text-wine" : "text-muted-foreground hover:text-foreground")}
          >
            {s.label}
            {active === s.key && <span className="absolute inset-x-2 bottom-0 h-0.5 rounded-full bg-wine" />}
          </button>
        ))}
      </div>
      {active === "users" && can(me.data, "users.manage") && <OnboardPerson />}
      {active === "users" && <UsersSection canEdit={can(me.data, "roles.manage")} />}
      {active === "teams" && <TeamsSection />}
      {active === "walls" && <WallsSection />}
      {active === "requests" && <RequestsSection />}
      {active === "import" && <ImportSection />}
      {active === "archive" && <ArchiveSection />}
    </div>
  );
}

function useRun() {
  const { toast } = useApp();
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      if (done) toast(done);
      return true;
    } catch (err) {
      toast(err instanceof Error ? err.message : "The change was not saved");
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { busy, run };
}

/** Onboard someone: profile and firm roles (their sign-in key is issued separately). */
function OnboardPerson() {
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const roles = useFirmRoles();
  const { busy, run } = useRun();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [title, setTitle] = useState("Associate");
  const [office, setOffice] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("fee_earner");
  const [error, setError] = useState<string | null>(null);
  if (!open) {
    return (
      <Button size="sm" onClick={() => setOpen(true)} data-testid="admin-onboard">
        Add a person
      </Button>
    );
  }
  const submit = async () => {
    setError(null);
    const ok = await run(async () => {
      try {
        await createPerson({ name, role: title, office: office || undefined, email: email || undefined, roles: [role] });
      } catch (err) {
        setError(firmError(err));
        throw err;
      }
      await queryClient.invalidateQueries({ queryKey: [identityKey, "admin-users"] });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "people"] });
    }, `${name} added`);
    if (ok) {
      setOpen(false);
      setName("");
      setEmail("");
    }
  };
  return (
    <section className="space-y-2 rounded-lg border border-border bg-card p-4" data-testid="admin-onboard-form">
      <SectionLabel>Add a person</SectionLabel>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Full name">{(f) => <Input {...f} value={name} onChange={(e) => setName(e.target.value)} data-testid="onboard-name" />}</Field>
        <Field label="Title" hint="For example: Associate.">{(f) => <Input {...f} value={title} onChange={(e) => setTitle(e.target.value)} />}</Field>
        <Field label="Office">{(f) => <Input {...f} value={office} onChange={(e) => setOffice(e.target.value)} />}</Field>
        <Field label="Email">{(f) => <Input {...f} type="email" value={email} onChange={(e) => setEmail(e.target.value)} />}</Field>
        <Field label="Firm role">
          {(f) => (
            <select {...f} className="w-full rounded-md border border-border bg-background px-2 py-2 text-sm" value={role} onChange={(e) => setRole(e.target.value)}>
              {(roles.data ?? []).map((r) => <option key={r.role_key} value={r.role_key}>{r.name}</option>)}
            </select>
          )}
        </Field>
      </div>
      {error && <p className="text-sm text-destructive">{error}</p>}
      <div className="flex gap-2">
        <Button size="sm" disabled={busy || !name.trim()} onClick={() => void submit()} data-testid="onboard-save">Add</Button>
        <Button size="sm" variant="outline" onClick={() => setOpen(false)}>Cancel</Button>
      </div>
    </section>
  );
}

function UsersSection({ canEdit }: { canEdit: boolean }) {
  const users = useAdminUsers();
  const roles = useFirmRoles();
  const [q, setQ] = useState("");
  if (users.isPending || roles.isPending) return <TableSkeleton />;
  if (users.isError) return <EmptyState icon="lock" title="You cannot view firm users" />;
  const list = (users.data ?? []).filter((u) => !q || `${u.name} ${u.role} ${u.office ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>{list.length} people</SectionLabel>
        <Input className="w-64" placeholder="Filter people" aria-label="Filter people" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <DataTable
        testId="admin-users"
        rows={list}
        getRowKey={(u) => u.member_id}
        empty={<EmptyState title="No people match" />}
        columns={[
          {
            key: "person",
            header: "Person",
            render: (u) => (
              <div>
                <Link to={`/people/${u.member_id}`} className="hover:text-wine">{u.name}</Link>{u.active === false && <span className="ml-2 rounded bg-secondary px-1.5 text-xs text-muted-foreground" data-testid="user-deactivated">Deactivated</span>}
                <div className="text-xs text-muted-foreground">{u.role} · {u.matter_count} matters</div>
              </div>
            ),
          },
          { key: "office", secondary: true, header: "Office", render: (u) => <span className="text-muted-foreground">{u.office ?? "—"}</span> },
          { key: "teams", secondary: true, header: "Teams", render: (u) => <span className="text-xs text-muted-foreground">{u.teams.join(", ") || "—"}</span> },
          { key: "roles", header: "Firm roles", render: (u) => <RoleChips user={u} roles={roles.data ?? []} canEdit={canEdit} /> },
        ]}
      />
    </section>
  );
}

function RoleChips({ user, roles, canEdit }: { user: AdminUser; roles: FirmRole[]; canEdit: boolean }) {
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const { busy, run } = useRun();
  const toggle = (role: string) => {
    const next = user.roles.includes(role) ? user.roles.filter((r) => r !== role) : [...user.roles, role];
    void run(() => setUserRoles(user.member_id, next), "Roles updated").then(() =>
      queryClient.invalidateQueries({ queryKey: [identityKey, "admin-users"] }),
    );
  };
  return (
    <div className="flex flex-wrap gap-1">
      {roles.map((r) => {
        const on = user.roles.includes(r.role_key);
        return (
          <button
            key={r.role_key}
            type="button"
            title={r.description}
            aria-pressed={on}
            disabled={!canEdit || busy}
            onClick={() => toggle(r.role_key)}
            data-testid={`role-${user.member_id}-${r.role_key}`}
            className={cn(
              "rounded-full border px-2 py-0.5 text-xs",
              on ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground",
              canEdit && "hover:border-wine/50",
            )}
          >
            {r.name}
          </button>
        );
      })}
    </div>
  );
}

function TeamsSection() {
  const teams = useTeams();
  const people = usePeople();
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const { busy, run } = useRun();
  const confirm = useConfirm();
  const [name, setName] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: [identityKey, "admin-teams"] });

  if (teams.isPending) return <TableSkeleton />;
  return (
    <section className="space-y-6">
      <div className="flex items-end gap-2">
        <Input className="w-72" placeholder="New team name (e.g. Delhi energy disputes)" value={name} onChange={(e) => setName(e.target.value)} />
        <Button
          disabled={busy || name.trim().length < 2}
          data-testid="team-create"
          onClick={() => void run(() => createTeam({ name: name.trim(), kind: "custom" }), "Team created").then((ok) => { if (ok) { setName(""); void refresh(); } })}
        >
          Create team
        </Button>
      </div>
      <div className="grid gap-4 md:grid-cols-2" data-testid="admin-teams">
        {(teams.data ?? []).map((t) => (
          <div key={t.team_id} className="rounded-lg border border-border bg-card p-4">
            <div className="flex items-start justify-between gap-2">
              <div>
                <div className="font-semibold text-ink">{t.name}</div>
                <div className="text-xs text-muted-foreground">{t.kind} · {t.member_count} members</div>
              </div>
              {t.kind === "custom" && (
                <Button size="sm" variant="ghost" disabled={busy} onClick={async () => {
                  if (await confirm({ title: `Delete the team “${t.name}”?`, description: "Members keep their access through other teams and roles.", confirmLabel: "Delete team" }))
                    void run(() => deleteTeam(t.team_id), "Team deleted").then(refresh);
                }}>
                  Delete
                </Button>
              )}
            </div>
            <ul className="mt-3 flex flex-wrap gap-1.5">
              {t.members.map((m) => (
                <li key={m.member_id} className="flex items-center gap-1 rounded-md border border-border px-2 py-0.5 text-xs">
                  {m.name}
                  <button type="button" aria-label={`Remove ${m.name}`} className="text-muted-foreground hover:text-wine" disabled={busy}
                    onClick={() => void run(() => setTeamMember(t.team_id, m.member_id, false)).then(refresh)}>
                    ×
                  </button>
                </li>
              ))}
            </ul>
            <select
              className="mt-3 h-8 w-full rounded-md border border-input bg-transparent px-2 text-xs"
              value=""
              disabled={busy}
              aria-label={`Add to ${t.name}`}
              onChange={(e) => e.target.value && void run(() => setTeamMember(t.team_id, e.target.value, true)).then(refresh)}
            >
              <option value="">Add a person…</option>
              {(people.data ?? []).filter((p) => !t.members.some((m) => m.member_id === p.member_id)).map((p) => (
                <option key={p.member_id} value={p.member_id}>{p.name} · {p.role}</option>
              ))}
            </select>
          </div>
        ))}
      </div>
    </section>
  );
}

function WallsSection() {
  const walls = useWalls();
  if (walls.isPending) return <TableSkeleton />;
  if (walls.isError) return <EmptyState icon="lock" title="You cannot view ethical walls" />;
  if (!walls.data?.length) return <EmptyState icon="shield" title="No restricted or team-only matters, and no screens" />;
  return (
    <table className="w-full text-sm" data-testid="admin-walls">
      <thead className="text-left text-xs text-muted-foreground">
        <tr>
          <th className="py-2">Matter</th>
          <th>Client</th>
          <th>Visibility</th>
          <th>Can open</th>
          <th>Screened</th>
          <th>Requests</th>
        </tr>
      </thead>
      <tbody className="divide-y divide-border">
        {walls.data.map((w) => (
          <tr key={w.matter_id}>
            <td className="py-2">
              <Link to={`/matters/${w.matter_id}`} className="hover:text-wine">{w.title}</Link>
              <div><MonoId className="text-xs">{w.matter_code}</MonoId></div>
            </td>
            <td className="text-muted-foreground">{w.client_name}</td>
            <td>
              <StatusLabel status={w.mode === "restricted" ? "Restricted" : w.mode === "team" ? "Team" : "Open"} />
              {w.hide_existence && <span className="ml-1 text-xs text-muted-foreground">hidden</span>}
            </td>
            <td>{w.mode === "open" ? "All" : w.allowed}</td>
            <td>{w.screened}</td>
            <td>{w.pending_requests}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function RequestsSection() {
  const requests = useAccessRequests("to_decide");
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const { busy, run } = useRun();
  if (requests.isPending) return <TableSkeleton />;
  if (!requests.data?.length) return <EmptyState icon="inbox" title="No pending access requests" />;
  const decide = (id: string, approve: boolean) =>
    void run(() => decideRequest(id, { approve }), approve ? "Access granted" : "Request declined").then(() =>
      queryClient.invalidateQueries({ queryKey: [identityKey, "access-requests"] }),
    );
  return (
    <ul className="divide-y divide-border rounded-lg border border-border" data-testid="admin-requests">
      {requests.data.map((r) => (
        <li key={r.request_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
          <div>
            <div className="text-sm font-medium">{r.requester_name} → <Link to={`/matters/${r.matter_id}`} className="hover:text-wine">{r.matter_title}</Link></div>
            <div className="text-xs text-muted-foreground">{r.level} · {r.reason}</div>
          </div>
          <div className="flex gap-2">
            <Button size="sm" disabled={busy} onClick={() => decide(r.request_id, true)}>Approve</Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => decide(r.request_id, false)}>Decline</Button>
          </div>
        </li>
      ))}
    </ul>
  );
}

const IMPORTS: { key: ImportEntity; label: string; hint: string; permission: string }[] = [
  { key: "clients", label: "Clients", hint: "Each new client name is checked for conflicts first. Names with possible conflicts are left for the conflict queue.", permission: "clients.create" },
  { key: "people", label: "People", hint: "Name is required. Roles are separated by semicolons, for example fee_earner; knowledge_manager.", permission: "users.manage" },
  { key: "matters", label: "Matters", hint: "The client must already exist and be active. The lead is found by email; if left empty, you lead the matter.", permission: "matters.create" },
];

/** Bring clients, people or matters in from a CSV file: check it first, then import what passes. */
function ImportSection() {
  const me = useMyAccess();
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const allowed = IMPORTS.filter((i) => can(me.data, i.permission));
  const [entity, setEntity] = useState<ImportEntity | null>(null);
  const [file, setFile] = useState<File | null>(null);
  const [report, setReport] = useState<ImportReport | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const current = allowed.find((i) => i.key === (entity ?? allowed[0]?.key));
  if (!current) return <EmptyState icon="lock" title="You cannot import data" />;

  const pick = (key: ImportEntity) => { setEntity(key); setFile(null); setReport(null); setError(null); };
  const go = async (dry: boolean) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      const out = await importFile(current.key, file, dry);
      setReport(out);
      if (!dry) {
        toast(`${out.created} ${out.created === 1 ? "row" : "rows"} imported`);
        queryClient.invalidateQueries();
      }
    } catch (err) {
      setError(firmError(err));
    } finally {
      setBusy(false);
    }
  };
  const applied = report !== null && report.created > 0;
  const pending = report !== null && !applied;

  return (
    <section className="space-y-5" data-testid="admin-import">
      <div className="flex flex-wrap gap-2" role="tablist" aria-label="What to import">
        {allowed.map((i) => (
          <Button key={i.key} size="sm" variant={i.key === current.key ? "default" : "outline"} role="tab" aria-selected={i.key === current.key}
            onClick={() => pick(i.key)} data-testid={`import-entity-${i.key}`}>{i.label}</Button>
        ))}
      </div>
      <p className="max-w-[65ch] text-sm text-muted-foreground">{current.hint}</p>
      <div className="flex flex-wrap items-center gap-3">
        <Button variant="outline" size="sm" onClick={() => downloadFile(`/api/imports/${current.key}/template`, `${current.key}-template.csv`)} data-testid="import-template">
          Download the template
        </Button>
        <input type="file" accept=".csv,text/csv" aria-label="CSV file" data-testid="import-file"
          onChange={(e) => { setFile(e.target.files?.[0] ?? null); setReport(null); setError(null); }}
          className="text-sm file:mr-3 file:rounded-md file:border file:border-border file:bg-card file:px-3 file:py-1.5 file:text-sm" />
        <Button size="sm" disabled={!file || busy} onClick={() => go(true)} data-testid="import-check">Check the file</Button>
      </div>
      {error && <p role="alert" className="text-sm text-destructive" data-testid="import-error">{error}</p>}
      {report && (
        <div className="space-y-3" data-testid="import-report">
          <p className="text-sm" aria-live="polite">
            {applied
              ? <>{report.created} imported. {report.errors + report.review} not imported.</>
              : <>{report.total} rows: <strong>{report.ok}</strong> can be imported{report.review > 0 && <>, {report.review} need conflict review</>}{report.errors > 0 && <>, {report.errors} have problems</>}. Nothing is saved yet.</>}
          </p>
          {pending && report.ok > 0 && (
            <Button size="sm" disabled={busy} onClick={() => go(false)} data-testid="import-apply">
              Import {report.ok} {report.ok === 1 ? "row" : "rows"}
            </Button>
          )}
          <div className="overflow-x-auto rounded-md border border-border">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted-foreground"><tr><th className="px-3 py-2">Row</th><th className="px-3 py-2">Name</th><th className="px-3 py-2">Result</th></tr></thead>
              <tbody>
                {report.rows.map((r) => (
                  <tr key={r.row} className="border-t border-border" data-testid={`import-row-${r.status}`}>
                    <td className="px-3 py-2 tabular-nums">{r.row}</td>
                    <td className="px-3 py-2">{r.label}</td>
                    <td className={cn("px-3 py-2", r.status === "error" ? "text-destructive" : r.status === "review" ? "text-warning-ink" : "text-success-ink")}>
                      {r.status === "ok" ? "Ready" : r.status === "created" ? "Imported" : r.message}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </section>
  );
}

/** Archived documents: hidden everywhere until an administrator restores them. */
function ArchiveSection() {
  const queryClient = useQueryClient();
  const { toast } = useApp();
  const archived = useQuery({ queryKey: ["archived-documents"], queryFn: fetchArchived });
  if (archived.isPending) return <TableSkeleton />;
  const items = archived.data ?? [];
  if (!items.length) return <EmptyState icon="archive" title="No archived documents" />;
  const restore = async (id: string) => {
    try {
      await restoreDocument(id);
      toast("Document restored");
      queryClient.invalidateQueries();
    } catch (err) {
      toast(firmError(err));
    }
  };
  return (
    <ul className="divide-y divide-border rounded-md border border-border" data-testid="admin-archive">
      {items.map((d) => (
        <li key={d.document_id} className="flex flex-wrap items-center gap-3 px-4 py-3 text-sm">
          <div className="min-w-0 flex-1">
            <div className="truncate font-medium">{d.title}</div>
            <div className="text-xs text-muted-foreground">
              {d.matter_title} · archived {d.archived_by_name ? `by ${d.archived_by_name}` : ""}{d.archive_reason ? `: ${d.archive_reason}` : ""}
            </div>
          </div>
          <Button size="sm" variant="outline" onClick={() => restore(d.document_id)} data-testid="archive-restore">Restore</Button>
        </li>
      ))}
    </ul>
  );
}
