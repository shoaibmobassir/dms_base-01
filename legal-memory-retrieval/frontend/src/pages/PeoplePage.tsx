import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { usePeople } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { PersonAvatar } from "@/components/common/EntityLink";
import { EmptyState, PageHeader, SearchField } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { initials } from "@/context/AppContext";
import { cn } from "@/lib/utils";

export function PeoplePage() {
  const navigate = useNavigate();
  const people = usePeople();
  const [query, setQuery] = useState("");
  const [practice, setPractice] = useState("");

  // The directory is small (one row per member) and returned whole by the API.
  const filter = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (p: { name: string; role: string; office: string | null; practice_areas: string[] }) =>
      (!practice || p.practice_areas.includes(practice)) &&
      (!q || [p.name, p.role, p.office ?? "", ...p.practice_areas].some((v) => v.toLowerCase().includes(q)));
  }, [query, practice]);
  const practices = useMemo(
    () => [...new Set((people.data ?? []).flatMap((p) => p.practice_areas))].sort(),
    [people.data],
  );

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="People"
        count={people.data ? `${people.data.length} people` : undefined}
        subtitle="Everyone in the firm, with the practices they work in and the open matters they are on."
      />
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="flex-1">
          <SearchField value={query} onChange={setQuery} placeholder="Search by name, role, office or practice…" testId="people-search" />
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Practice">
          {["", ...practices].map((p) => (
            <button
              key={p || "all"}
              type="button"
              onClick={() => setPractice(p)}
              aria-pressed={practice === p}
              data-testid={`people-practice-${p || "all"}`}
              className={cn(
                "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
                practice === p ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary",
              )}
            >
              {p || "All"}
            </button>
          ))}
        </div>
      </div>
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
                {
                  key: "current",
                  header: "Open matters",
                  align: "right",
                  render: (p) => <span className="text-sm tabular-nums">{p.current_matters ?? "—"}</span>,
                },
                { key: "office", header: "Office", align: "right", render: (p) => p.office || "—" },
              ]}
            />
          );
        }}
      </QueryState>
    </div>
  );
}
