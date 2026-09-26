import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useDeadlines } from "@/api/resources";
import type { Deadline } from "@/api/types";
import { DataTable } from "@/components/common/DataTable";
import { EmptyState, Icon, PageHeader, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { cn } from "@/lib/utils";

const FILTERS: { label: string; value: "open" | "done" | "all" }[] = [
  { label: "Open", value: "open" },
  { label: "Done", value: "done" },
  { label: "All", value: "all" },
];

/** "in 3 days", "today", "2 days ago" — relative to the viewer's clock. */
export function dueLabel(iso: string) {
  const due = new Date(`${iso}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

function isOverdue(d: Deadline) {
  return d.status === "open" && dueLabel(d.due).endsWith("ago");
}

export function CalendarPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState<"open" | "done" | "all">("open");
  const [view, setView] = useState<"list" | "month">("list");
  const query = useDeadlines({ status });

  return (
    <div className="space-y-8">
      <PageHeader
        eyebrow="Calendar"
        title="What's coming up."
        subtitle="Hearings, filings and compliance dates across the matters you can access."
      />

      <div className="flex flex-wrap items-center gap-1.5">
        <div className="mr-3 inline-flex overflow-hidden rounded-md border border-border" role="tablist" aria-label="View">
          {(["list", "month"] as const).map((v) => (
            <button
              key={v}
              type="button"
              role="tab"
              aria-selected={view === v}
              onClick={() => setView(v)}
              data-testid={`calendar-view-${v}`}
              className={cn(
                "px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                view === v ? "bg-wine-soft text-wine" : "text-muted-foreground hover:bg-secondary",
              )}
            >
              {v}
            </button>
          ))}
        </div>
        {FILTERS.map((f) => (
          <button
            key={f.value}
            type="button"
            onClick={() => setStatus(f.value)}
            className={cn(
              "rounded-full border px-3 py-1.5 text-xs font-medium transition-colors",
              status === f.value ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary",
            )}
          >
            {f.label}
          </button>
        ))}
      </div>

      <QueryState
        query={query}
        isEmpty={(rows) => rows.length === 0}
        empty={<EmptyState icon="event" title="No deadlines" description="Nothing matches this filter within your access scope." />}
      >
        {(rows) =>
          view === "month" ? (
            <MonthGrid rows={rows} onOpen={(d) => navigate(`/matters/${d.matter_id}`)} />
          ) : (
          <DataTable
            testId="deadlines-table"
            rows={rows}
            getRowKey={(d) => d.id}
            onRowClick={(d) => navigate(`/matters/${d.matter_id}`)}
            columns={[
              {
                key: "due",
                header: "Due",
                width: 150,
                render: (d) => (
                  <div>
                    <div className={cn("font-mono-id text-sm", isOverdue(d) ? "text-destructive" : "text-foreground")}>{d.due}</div>
                    <div className="text-xs text-muted-foreground">{dueLabel(d.due)}</div>
                  </div>
                ),
              },
              {
                key: "title",
                header: "Deadline",
                render: (d) => (
                  <div>
                    <div className="text-foreground">{d.title}</div>
                    <div className="text-xs capitalize text-muted-foreground">{d.kind}</div>
                  </div>
                ),
              },
              {
                key: "matter",
                secondary: true,
                header: "Matter",
                render: (d) => (
                  <div>
                    <div className="font-mono-id text-xs text-muted-foreground">{d.matter_code}</div>
                    <div className="text-sm">{d.matter_title}</div>
                  </div>
                ),
              },
              { key: "court", secondary: true, header: "Forum", render: (d) => <span className="text-sm text-muted-foreground">{d.court || "—"}</span> },
              { key: "owner", secondary: true, header: "Owner", render: (d) => <span className="text-sm">{d.owner_name || "—"}</span> },
              { key: "status", header: "Status", align: "right", render: (d) => <StatusLabel status={d.status === "done" ? "Resolved" : "Open"} /> },
            ]}
          />
          )
        }
      </QueryState>
    </div>
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}

/** Month grid (weeks start Monday). Opens on the month of the first listed deadline. */
function MonthGrid({ rows, onOpen }: { rows: Deadline[]; onOpen: (d: Deadline) => void }) {
  const [cursor, setCursor] = useState(() => {
    const first = rows[0] ? new Date(`${rows[0].due}T00:00:00`) : new Date();
    return new Date(first.getFullYear(), first.getMonth(), 1);
  });
  const byDay = useMemo(() => {
    const m = new Map<string, Deadline[]>();
    for (const r of rows) m.set(r.due, [...(m.get(r.due) ?? []), r]);
    return m;
  }, [rows]);

  const start = new Date(cursor);
  start.setDate(1 - ((cursor.getDay() + 6) % 7));
  const days = Array.from({ length: 42 }, (_, i) => new Date(start.getFullYear(), start.getMonth(), start.getDate() + i));
  const today = isoDay(new Date());
  const shift = (n: number) => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + n, 1));

  return (
    <div data-testid="calendar-month">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="font-display text-2xl text-ink">
          {cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
        </h2>
        <div className="flex gap-1">
          <button type="button" aria-label="Previous month" onClick={() => shift(-1)} className="rounded-md p-1.5 hover:bg-secondary">
            <Icon name="chevron_left" />
          </button>
          <button type="button" aria-label="Next month" onClick={() => shift(1)} className="rounded-md p-1.5 hover:bg-secondary">
            <Icon name="chevron_right" />
          </button>
        </div>
      </div>
      <div className="grid grid-cols-7 border-l border-t border-border text-sm">
        {WEEKDAYS.map((w) => (
          <div key={w} className="meta-label border-b border-r border-border px-2 py-1.5 text-[10px]">
            {w}
          </div>
        ))}
        {days.map((d) => {
          const key = isoDay(d);
          const items = byDay.get(key) ?? [];
          const inMonth = d.getMonth() === cursor.getMonth();
          return (
            <div
              key={key}
              className={cn("min-h-[92px] border-b border-r border-border p-1.5", !inMonth && "bg-secondary/40 text-muted-foreground")}
            >
              <div className={cn("mb-1 font-mono-id text-xs", key === today && "inline-block rounded bg-wine px-1 text-primary-foreground")}>
                {d.getDate()}
              </div>
              <div className="space-y-1">
                {items.map((it) => (
                  <button
                    key={it.id}
                    type="button"
                    onClick={() => onOpen(it)}
                    title={`${it.title} · ${it.matter_code}`}
                    className={cn(
                      "block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px]",
                      it.status === "done" ? "bg-secondary text-muted-foreground line-through" : isOverdue(it) ? "bg-destructive/10 text-destructive" : "bg-wine-soft text-wine",
                    )}
                  >
                    {it.title}
                  </button>
                ))}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
