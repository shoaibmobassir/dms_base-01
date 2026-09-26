import { useState } from "react";
import { Link } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
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
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { EmptyState, MonoId, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

type Section = "users" | "teams" | "walls" | "requests";

const SECTIONS: { key: Section; label: string; permission: string[] }[] = [
  { key: "users", label: "Users & roles", permission: ["users.manage", "roles.manage", "walls.manage"] },
  { key: "teams", label: "Teams", permission: ["teams.manage"] },
  { key: "walls", label: "Ethical walls", permission: ["walls.manage", "audit.read"] },
  { key: "requests", label: "Access requests", permission: ["access_requests.decide", "walls.manage"] },
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
      <PageHeader eyebrow="Manage" title="Administration" subtitle="People, roles, teams and who can see which matters. Every change is audited." />
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
      {active === "users" && <UsersSection canEdit={can(me.data, "roles.manage")} />}
      {active === "teams" && <TeamsSection />}
      {active === "walls" && <WallsSection />}
      {active === "requests" && <RequestsSection />}
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

function UsersSection({ canEdit }: { canEdit: boolean }) {
  const users = useAdminUsers();
  const roles = useFirmRoles();
  const [q, setQ] = useState("");
  if (users.isPending || roles.isPending) return <p className="text-sm text-muted-foreground">Loading people…</p>;
  if (users.isError) return <EmptyState icon="lock" title="You cannot view firm users" />;
  const list = (users.data ?? []).filter((u) => !q || `${u.name} ${u.role} ${u.office ?? ""}`.toLowerCase().includes(q.toLowerCase()));
  return (
    <section className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <SectionLabel>{list.length} people</SectionLabel>
        <Input className="w-64" placeholder="Filter people" value={q} onChange={(e) => setQ(e.target.value)} />
      </div>
      <table className="w-full text-sm" data-testid="admin-users">
        <thead className="text-left text-xs text-muted-foreground">
          <tr>
            <th className="py-2">Person</th>
            <th>Office</th>
            <th>Teams</th>
            <th>Firm roles</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-border">
          {list.map((u) => (
            <UserRow key={u.member_id} user={u} roles={roles.data ?? []} canEdit={canEdit} />
          ))}
        </tbody>
      </table>
    </section>
  );
}

function UserRow({ user, roles, canEdit }: { user: AdminUser; roles: FirmRole[]; canEdit: boolean }) {
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
    <tr>
      <td className="py-2">
        <Link to={`/people/${user.member_id}`} className="hover:text-wine">{user.name}</Link>
        <div className="text-xs text-muted-foreground">{user.role} · {user.matter_count} matters</div>
      </td>
      <td className="text-muted-foreground">{user.office ?? "—"}</td>
      <td className="max-w-[16rem] text-xs text-muted-foreground">{user.teams.join(", ") || "—"}</td>
      <td>
        <div className="flex flex-wrap gap-1">
          {roles.map((r) => {
            const on = user.roles.includes(r.role_key);
            return (
              <button
                key={r.role_key}
                type="button"
                title={r.description}
                disabled={!canEdit || busy}
                onClick={() => toggle(r.role_key)}
                data-testid={`role-${user.member_id}-${r.role_key}`}
                className={cn(
                  "rounded-full border px-2 py-0.5 text-[11px]",
                  on ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground",
                  canEdit && "hover:border-wine/50",
                )}
              >
                {r.name}
              </button>
            );
          })}
        </div>
      </td>
    </tr>
  );
}

function TeamsSection() {
  const teams = useTeams();
  const people = usePeople();
  const { identityKey } = useApp();
  const queryClient = useQueryClient();
  const { busy, run } = useRun();
  const [name, setName] = useState("");
  const refresh = () => queryClient.invalidateQueries({ queryKey: [identityKey, "admin-teams"] });

  if (teams.isPending) return <p className="text-sm text-muted-foreground">Loading teams…</p>;
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
                <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => deleteTeam(t.team_id), "Team deleted").then(refresh)}>
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
  if (walls.isPending) return <p className="text-sm text-muted-foreground">Loading walls…</p>;
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
              <div><MonoId className="text-[11px]">{w.matter_code}</MonoId></div>
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
  if (requests.isPending) return <p className="text-sm text-muted-foreground">Loading requests…</p>;
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
