import { useNavigate, useParams } from "react-router-dom";
import { usePerson } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { PersonAvatar } from "@/components/common/EntityLink";
import { EmptyState, PageHeader, SectionLabel, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { initials } from "@/context/AppContext";

export function PersonDetailPage() {
  const { id = "" } = useParams();
  const navigate = useNavigate();
  const person = usePerson(id);

  return (
    <QueryState query={person} loading={<p className="text-sm text-muted-foreground">Loading…</p>}>
      {({ person: p, matters }) => (
        <div className="space-y-10">
          <PageHeader eyebrow={p.role} title={p.name} subtitle={[p.practice_areas.join(", "), p.office].filter(Boolean).join(" · ")}>
            <div className="mt-4 flex flex-wrap items-center gap-4 text-sm text-muted-foreground">
              <PersonAvatar person={{ name: p.name, initials: initials(p.name) }} size={44} />
              {p.joined_year && <span>Joined {p.joined_year}</span>}
              {p.specializations.length > 0 && <span>{p.specializations.join(" · ")}</span>}
            </div>
          </PageHeader>

          <section>
            <SectionLabel>Matters you can see</SectionLabel>
            <DataTable
              testId="person-matters"
              getRowKey={(m) => m.matter_id}
              onRowClick={(m) => navigate(`/matters/${m.matter_id}`)}
              rows={matters}
              empty={<EmptyState title="No matters in your scope" description="This person's matters are either none or outside your access scope." />}
              columns={[
                {
                  key: "matter",
                  header: "Matter",
                  render: (m) => (
                    <div>
                      <div className="font-mono-id text-xs text-muted-foreground">{m.matter_code}</div>
                      <div>{m.title}</div>
                    </div>
                  ),
                },
                { key: "role", header: "Role", render: (m) => m.role_on_matter },
                { key: "status", header: "Status", align: "right", render: (m) => <StatusLabel status={m.status || "Open"} /> },
              ]}
            />
          </section>
        </div>
      )}
    </QueryState>
  );
}
