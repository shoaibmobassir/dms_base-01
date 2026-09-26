import { useState, type ReactNode } from "react";
import { useQueryClient } from "@tanstack/react-query";
import {
  addGrant,
  addScreen,
  decideRequest,
  removeGrant,
  removeScreen,
  setMatterMode,
  useMatterAccess,
  useTeams,
  type AccessLevel,
  type AccessMode,
} from "@/api/access";
import { usePeople } from "@/api/resources";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { EmptyState, Icon, SectionLabel } from "@/components/common/primitives";
import { useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

const MODES: { mode: AccessMode; title: string; body: string; icon: string }[] = [
  { mode: "open", title: "Firm-open", body: "Every lawyer in the firm can find and read this matter.", icon: "public" },
  { mode: "team", title: "Team", body: "The matter team plus people and teams granted access.", icon: "groups" },
  { mode: "restricted", title: "Restricted (wall)", body: "Only people and teams granted below. Staffing alone does not pass the wall.", icon: "lock" },
];

const LEVEL_LABEL: Record<AccessLevel, string> = { read: "Read", edit: "Edit", manage: "Manage" };
const selectCls =
  "h-9 rounded-md border border-input bg-transparent px-2 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring";

/** Who can see this matter, and the controls to change it (matter managers, risk & compliance). */
export function MatterAccessTab({ matterId }: { matterId: string }) {
  const access = useMatterAccess(matterId);
  const people = usePeople();
  const teams = useTeams();
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);

  const refresh = () =>
    Promise.all([
      queryClient.invalidateQueries({ queryKey: [identityKey, "matter-access", matterId] }),
      queryClient.invalidateQueries({ queryKey: [identityKey, "matter", matterId] }),
    ]);

  const run = async (fn: () => Promise<unknown>, done?: string) => {
    setBusy(true);
    try {
      await fn();
      await refresh();
      if (done) toast(done);
    } catch (err) {
      toast(err instanceof Error ? err.message : "The change was not saved");
    } finally {
      setBusy(false);
    }
  };

  if (access.isPending) return <p className="text-sm text-muted-foreground">Loading access…</p>;
  if (access.isError || !access.data) {
    return <EmptyState icon="lock" title="Access settings are available to this matter's managers" />;
  }
  const a = access.data;

  return (
    <div className="space-y-10" data-testid="matter-access">
      <section>
        <SectionLabel>Who can see this matter</SectionLabel>
        <div className="grid gap-3 md:grid-cols-3">
          {MODES.map((m) => (
            <button
              key={m.mode}
              type="button"
              disabled={busy || a.mode === m.mode}
              onClick={() =>
                void run(
                  () => setMatterMode(matterId, { mode: m.mode, row_version: a.row_version }),
                  `Matter is now ${m.title.toLowerCase()}`,
                )
              }
              data-testid={`access-mode-${m.mode}`}
              className={cn(
                "rounded-lg border p-4 text-left transition-colors",
                a.mode === m.mode ? "border-wine bg-wine-soft/40" : "border-border bg-card hover:border-wine/40",
              )}
            >
              <div className="flex items-center gap-2 text-sm font-semibold text-ink">
                <Icon name={m.icon} style={{ fontSize: 18 }} className={a.mode === m.mode ? "text-wine" : "text-muted-foreground"} />
                {m.title}
              </div>
              <p className="mt-1 text-xs text-muted-foreground">{m.body}</p>
            </button>
          ))}
        </div>
        {a.mode !== "open" && (
          <label className="mt-4 flex items-center gap-3 text-sm">
            <Switch
              checked={a.hide_existence}
              disabled={busy}
              onCheckedChange={(v) => void run(() => setMatterMode(matterId, { mode: a.mode, hide_existence: v, row_version: a.row_version }))}
              data-testid="access-hide-existence"
            />
            Hide that this matter exists from people outside it (no search results, counts or “request access”)
          </label>
        )}
        {a.compiled && (
          <p className="mt-3 text-xs text-muted-foreground" data-testid="access-summary">
            {a.mode === "open" ? "All lawyers" : `${a.compiled.allowed} people`} can open it
            {a.compiled.denied ? ` · ${a.compiled.denied} screened` : ""} · last changed by {a.updated_by ?? "—"}
          </p>
        )}
      </section>

      {a.pending_requests.length > 0 && (
        <section>
          <SectionLabel>Access requests ({a.pending_requests.length})</SectionLabel>
          <ul className="divide-y divide-border rounded-lg border border-border" data-testid="access-requests">
            {a.pending_requests.map((r) => (
              <li key={r.request_id} className="flex flex-wrap items-center justify-between gap-3 p-3">
                <div>
                  <div className="text-sm font-medium">
                    {r.requester_name} · {r.level}
                  </div>
                  <div className="text-xs text-muted-foreground">{r.reason}</div>
                </div>
                <div className="flex gap-2">
                  <Button size="sm" disabled={busy} onClick={() => void run(() => decideRequest(r.request_id, { approve: true }), "Access granted")}>
                    Approve
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => decideRequest(r.request_id, { approve: false }), "Request declined")}>
                    Decline
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        </section>
      )}

      <section>
        <SectionLabel>Matter team</SectionLabel>
        <p className="mb-2 text-xs text-muted-foreground">
          {a.mode === "restricted"
            ? "In a restricted matter the team needs grants below to pass the wall."
            : "The team can open this matter while it is firm-open or team-only."}
        </p>
        <ul className="flex flex-wrap gap-2">
          {a.team.map((t) => (
            <li key={t.member_id} className="rounded-md border border-border px-2.5 py-1 text-xs">
              {t.name} <span className="text-muted-foreground">· {t.role_on_matter ?? t.role}</span>
            </li>
          ))}
        </ul>
      </section>

      <section>
        <SectionLabel>Granted access</SectionLabel>
        {a.grants.length === 0 ? (
          <p className="text-sm text-muted-foreground">No individual or team grants.</p>
        ) : (
          <table className="w-full text-sm" data-testid="access-grants">
            <thead className="text-left text-xs text-muted-foreground">
              <tr>
                <th className="py-2">Person or team</th>
                <th>Level</th>
                <th>Reason</th>
                <th>Expires</th>
                <th />
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {a.grants.map((g) => (
                <tr key={g.grant_id}>
                  <td className="py-2">
                    {g.principal_name ?? g.principal_id}
                    {g.principal_type === "team" && <span className="text-xs text-muted-foreground"> · team of {g.team_size}</span>}
                  </td>
                  <td>{LEVEL_LABEL[g.level]}</td>
                  <td className="max-w-xs truncate text-muted-foreground">{g.reason || "—"}</td>
                  <td className="text-muted-foreground">{g.expires_at ? new Date(g.expires_at).toLocaleDateString() : "—"}</td>
                  <td className="text-right">
                    <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => removeGrant(matterId, g.grant_id), "Access removed")}>
                      Remove
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        <GrantForm
          busy={busy}
          people={(people.data ?? []).map((p) => ({ id: p.member_id, label: `${p.name} · ${p.role}` }))}
          teams={(teams.data ?? []).map((t) => ({ id: t.team_id, label: `${t.name} (${t.member_count})` }))}
          onAdd={(body) => run(() => addGrant(matterId, body), "Access granted")}
        />
      </section>

      {a.can_manage_screens && (
        <section>
          <SectionLabel>Screens (ethical wall exclusions)</SectionLabel>
          <p className="mb-2 text-xs text-muted-foreground">
            A screened person cannot see this matter anywhere — search, Ask the Firm, the Assistant, calendar or counts — even when it is firm-open.
          </p>
          {a.screens.length > 0 && (
            <ul className="mb-3 divide-y divide-border rounded-lg border border-border" data-testid="access-screens">
              {a.screens.map((s) => (
                <li key={s.member_id} className="flex items-center justify-between gap-3 p-3 text-sm">
                  <span>
                    {s.name} <span className="text-xs text-muted-foreground">· {s.reason}</span>
                  </span>
                  <Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => removeScreen(matterId, s.member_id), "Screen lifted")}>
                    Lift
                  </Button>
                </li>
              ))}
            </ul>
          )}
          <ScreenForm
            busy={busy}
            people={(people.data ?? []).map((p) => ({ id: p.member_id, label: `${p.name} · ${p.role}` }))}
            onAdd={(body) => run(() => addScreen(matterId, body), "Person screened")}
          />
        </section>
      )}

      {a.history.length > 0 && (
        <section>
          <SectionLabel>Change history</SectionLabel>
          <ul className="space-y-1 text-xs text-muted-foreground" data-testid="access-history">
            {a.history.slice(0, 15).map((h, i) => (
              <li key={i}>
                {new Date(h.occurred_at).toLocaleString()} · {h.member_id ?? "system"} · {h.action.replace("access.", "")}
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
}

type Option = { id: string; label: string };

function Row({ children }: { children: ReactNode }) {
  return <div className="mt-3 flex flex-wrap items-end gap-2">{children}</div>;
}

function GrantForm({
  busy,
  people,
  teams,
  onAdd,
}: {
  busy: boolean;
  people: Option[];
  teams: Option[];
  onAdd: (body: { principal_type: "member" | "team"; principal_id: string; level: AccessLevel; reason: string; expires_at: string | null }) => Promise<void>;
}) {
  const [type, setType] = useState<"member" | "team">("member");
  const [id, setId] = useState("");
  const [level, setLevel] = useState<AccessLevel>("read");
  const [reason, setReason] = useState("");
  const [expires, setExpires] = useState("");
  const options = type === "member" ? people : teams;
  return (
    <Row>
      <select className={selectCls} value={type} onChange={(e) => { setType(e.target.value as "member" | "team"); setId(""); }} aria-label="Grant to">
        <option value="member">Person</option>
        <option value="team">Team</option>
      </select>
      <select className={cn(selectCls, "min-w-56")} value={id} onChange={(e) => setId(e.target.value)} aria-label="Who" data-testid="grant-principal">
        <option value="">Choose…</option>
        {options.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
      <select className={selectCls} value={level} onChange={(e) => setLevel(e.target.value as AccessLevel)} aria-label="Level">
        <option value="read">Read</option>
        <option value="edit">Edit</option>
        <option value="manage">Manage</option>
      </select>
      <Input className="w-56" placeholder="Reason" value={reason} onChange={(e) => setReason(e.target.value)} />
      <Input className="w-40" type="date" value={expires} onChange={(e) => setExpires(e.target.value)} aria-label="Expires" />
      <Button
        disabled={busy || !id}
        data-testid="grant-add"
        onClick={() => void onAdd({ principal_type: type, principal_id: id, level, reason, expires_at: expires || null }).then(() => { setId(""); setReason(""); setExpires(""); })}
      >
        Grant access
      </Button>
    </Row>
  );
}

function ScreenForm({ busy, people, onAdd }: { busy: boolean; people: Option[]; onAdd: (body: { member_id: string; reason: string }) => Promise<void> }) {
  const [id, setId] = useState("");
  const [reason, setReason] = useState("");
  return (
    <Row>
      <select className={cn(selectCls, "min-w-56")} value={id} onChange={(e) => setId(e.target.value)} aria-label="Person to screen" data-testid="screen-member">
        <option value="">Choose a person…</option>
        {people.map((o) => (
          <option key={o.id} value={o.id}>{o.label}</option>
        ))}
      </select>
      <Input className="w-72" placeholder="Reason (required, e.g. acted for the counterparty)" value={reason} onChange={(e) => setReason(e.target.value)} />
      <Button variant="outline" disabled={busy || !id || reason.trim().length < 3} data-testid="screen-add"
        onClick={() => void onAdd({ member_id: id, reason }).then(() => { setId(""); setReason(""); })}>
        Screen
      </Button>
    </Row>
  );
}
