import { useEffect } from "react";
import { PersonAvatar } from "@/components/common/EntityLink";
import { PageHeader, SectionLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { useSystemInfo, useTeams } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { EmptyState, Icon } from "@/components/common/primitives";
import { useTheme, type Theme } from "@/lib/theme";
import { initials, useApp } from "@/context/AppContext";
import { cn } from "@/lib/utils";

export function SettingsPage() {
  // Deep links such as /settings#teams (the old /teams route redirects here).
  useEffect(() => {
    const id = window.location.hash.slice(1);
    if (id) document.getElementById(id)?.scrollIntoView();
  }, []);

  const { me, firm, authEnabled, personas, setPersona } = useApp();
  const info = useSystemInfo();
  const teams = useTeams();
  const { theme, setTheme } = useTheme();

  return (
    <div className="space-y-10">
      <PageHeader eyebrow="Settings" title="Settings" subtitle="Your identity, the firm, and how this deployment is configured." />

      <section className="max-w-2xl">
        <SectionLabel>Profile</SectionLabel>
        {me && (
          <div className="flex items-center gap-4">
            <PersonAvatar person={{ name: me.name, initials: initials(me.name) }} size={56} />
            <div>
              <div className="font-display text-2xl text-ink">{me.name}</div>
              <div className="text-sm text-muted-foreground">{[me.role, me.office, me.member_id].filter(Boolean).join(" · ")}</div>
            </div>
          </div>
        )}
        {!authEnabled && personas.length > 0 && (
          <div className="mt-6">
            <div className="meta-label mb-2">Viewing as (development mode)</div>
            <div className="grid gap-1 sm:grid-cols-2">
              {personas.map((p) => (
                <button
                  key={p.member_id}
                  type="button"
                  onClick={() => setPersona(p.member_id)}
                  className={cn(
                    "rounded-md px-3 py-2 text-left text-sm",
                    me?.member_id === p.member_id ? "bg-wine-soft text-wine" : "hover:bg-secondary",
                  )}
                >
                  {p.name} <span className="text-xs text-muted-foreground">· {p.role}</span>
                </button>
              ))}
            </div>
          </div>
        )}
      </section>

      <section className="max-w-2xl" id="appearance">
        <SectionLabel>Appearance</SectionLabel>
        <div className="grid grid-cols-3 gap-2" role="radiogroup" aria-label="Theme">
          {(
            [
              ["light", "Light", "light_mode"],
              ["dark", "Dark", "dark_mode"],
              ["system", "Match system", "contrast"],
            ] as [Theme, string, string][]
          ).map(([value, label, icon]) => (
            <button
              key={value}
              type="button"
              role="radio"
              aria-checked={theme === value}
              onClick={() => setTheme(value)}
              data-testid={`settings-theme-${value}`}
              className={cn(
                "flex items-center gap-2 rounded-md border px-3 py-2.5 text-sm transition-colors",
                theme === value ? "border-wine bg-wine-soft text-wine" : "border-border hover:bg-secondary",
              )}
            >
              <Icon name={icon} style={{ fontSize: 18 }} /> {label}
            </button>
          ))}
        </div>
        <p className="mt-2 text-xs text-muted-foreground">Saved in this browser.</p>
      </section>

      <section className="max-w-2xl">
        <SectionLabel>Firm</SectionLabel>
        <Row label="Name" value={firm?.name} />
        <Row label="Practice" value={firm?.descriptor} />
        <Row label="Office" value={firm?.office} />
      </section>

      <section className="max-w-2xl scroll-mt-8" id="teams">
        <SectionLabel>Teams</SectionLabel>
        <p className="mb-3 text-sm text-muted-foreground">Practice teams from the directory, with the open matters in your scope.</p>
        <QueryState query={teams} isEmpty={(t) => t.length === 0} empty={<EmptyState icon="groups" title="No practice teams in the directory" />}>
          {(rows) => (
            <DataTable
              testId="teams-table"
              getRowKey={(t) => t.name}
              rows={rows}
              columns={[
                { key: "name", header: "Practice", render: (t) => <span className="text-foreground">{t.name}</span> },
                { key: "lawyers", header: "Lawyers", render: (t) => t.lawyers },
                { key: "active", header: "Open matters", align: "right", render: (t) => t.active_matters },
              ]}
            />
          )}
        </QueryState>
      </section>

      <section className="max-w-2xl">
        <SectionLabel>System</SectionLabel>
        <QueryState query={info}>
          {(i) => (
            <>
              <Row label="Authentication" value={i.auth_enabled ? "API keys required" : "Development mode (member header trusted)"} />
              <Row label="Retrieval engine" value={i.retrieval_engine} />
              <Row label="Index version" value={i.index_version} />
              <Row label="Embeddings" value={i.embedding_version} />
              <Row
                label="Enabled features"
                value={Object.entries(i.features)
                  .filter(([, on]) => on)
                  .map(([k]) => k.replace(/_/g, " "))
                  .join(", ")}
              />
            </>
          )}
        </QueryState>
      </section>
    </div>
  );
}

function Row({ label, value }: { label: string; value?: string | null }) {
  return (
    <div className="grid grid-cols-3 gap-3 border-b border-border py-3 text-sm">
      <div className="meta-label pt-0.5">{label}</div>
      <div className="col-span-2 text-foreground">{value || "—"}</div>
    </div>
  );
}
