import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePeople } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { PersonAvatar } from "@/components/common/EntityLink";
import { EmptyState, PageHeader, SearchField } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { initials } from "@/context/AppContext";

export function PeoplePage() {
  const navigate = useNavigate();
  const people = usePeople();
  const [query, setQuery] = useState("");

  // The directory is small (one row per member) and returned whole by the API.
  const filter = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (p: { name: string; role: string; office: string | null; practice_areas: string[] }) =>
      !q || [p.name, p.role, p.office ?? "", ...p.practice_areas].some((v) => v.toLowerCase().includes(q));
  }, [query]);

  return (
    <div className="space-y-8">
      <PageHeader eyebrow="People" title="The people behind the matters." subtitle="Everyone in the firm directory, with the practices they work in." />
      <SearchField value={query} onChange={setQuery} placeholder="Search by name, role, office or practice…" testId="people-search" />
      <QueryState query={people}>
        {(rows) => {
          const visible = rows.filter(filter);
          return (
            <DataTable
              testId="people-table"
              getRowKey={(p) => p.member_id}
              onRowClick={(p) => navigate(`/people/${p.member_id}`)}
              rows={visible}
              empty={<EmptyState title="No people match" />}
              columns={[
                {
                  key: "name",
                  header: "Name",
                  render: (p) => (
                    <span className="flex items-center gap-3">
                      <PersonAvatar person={{ name: p.name, initials: initials(p.name) }} size={30} />
                      <span>
                        <span className="block text-foreground">{p.name}</span>
                        <span className="block text-xs text-muted-foreground">{p.role}</span>
                      </span>
                    </span>
                  ),
                },
                { key: "practice", secondary: true, header: "Practice", render: (p) => <span className="text-sm text-muted-foreground">{p.practice_areas.join(", ") || "—"}</span> },
                { key: "office", header: "Office", align: "right", render: (p) => p.office || "—" },
              ]}
            />
          );
        }}
      </QueryState>
    </div>
  );
}
