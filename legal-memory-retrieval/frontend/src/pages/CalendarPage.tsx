import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { apiFetch } from "@/api/client";
import { firmError } from "@/api/firm";
import { useMatters, usePeople } from "@/api/resources";
import { DataTable } from "@/components/common/DataTable";
import { Action, EmptyState, Icon, PageHeader, StatusLabel } from "@/components/common/primitives";
import { QueryState } from "@/components/common/QueryState";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useApp } from "@/context/AppContext";
import { formatDate } from "@/lib/format";
import { cn } from "@/lib/utils";

// Mirrors app/firm/calendar.py (plan 17, P3).
type Scope = "mine" | "team" | "matter" | "firm";
type View = "list" | "week" | "month";
export type CalItem = {
  id: string
  source: "deadline" | "event"
  title: string
  kind: string
  start: string
  end: string
  all_day: boolean
  matter_id: string | null
  matter_code: string | null
  matter_title: string | null
  owner_id: string | null
  owner_name: string | null
  attendees: string[]
  status: string
  location: string
  notes: string | null
  court?: string | null
  /** Court dates only: false until a second lawyer confirms; null when no confirmation applies. */
  confirmed: boolean | null
  confirmed_by?: string | null
  created_by?: string | null
  restricted: boolean
  row_version: number
  can_edit: boolean
}

const SCOPES: { key: Scope; label: string }[] = [
  { key: "mine", label: "Mine" },
  { key: "team", label: "My team" },
  { key: "matter", label: "Matter" },
  { key: "firm", label: "Firm" },
];
const STATUS = ["open", "done", "all"] as const;
const inputCls = "w-full rounded-md border border-border bg-card px-3 py-2 text-sm";
const EVENT_KINDS = ["meeting", "hearing", "filing", "internal", "out_of_office"];
const DEADLINE_KINDS = ["hearing", "filing", "limitation", "compliance"];

/** "in 3 days", "today", "2 days ago" — relative to the viewer's clock. */
export function dueLabel(iso: string) {
  const due = new Date(`${iso.slice(0, 10)}T00:00:00`);
  const today = new Date();
  today.setHours(0, 0, 0, 0);
  const days = Math.round((due.getTime() - today.getTime()) / 86_400_000);
  if (days === 0) return "today";
  if (days === 1) return "tomorrow";
  if (days === -1) return "yesterday";
  return days > 0 ? `in ${days} days` : `${-days} days ago`;
}

function isoDay(d: Date) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
const addDays = (d: Date, n: number) => new Date(d.getFullYear(), d.getMonth(), d.getDate() + n);
const dayOf = (it: CalItem) => (it.all_day ? it.start.slice(0, 10) : isoDay(new Date(it.start)));
const isOverdue = (it: CalItem) => it.source === "deadline" && it.status === "open" && dueLabel(it.start).endsWith("ago");
const timeOf = (it: CalItem) => (it.all_day ? "" : new Date(it.start).toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" }));

function tone(it: CalItem) {
  if (it.status === "done") return "bg-secondary text-muted-foreground line-through";
  if (isOverdue(it)) return "bg-destructive/10 text-destructive";
  if (it.confirmed === false) return "bg-amber-100 text-amber-900 dark:bg-amber-950/40 dark:text-amber-200";
  if (it.source === "event") return "bg-sky-100 text-sky-900 dark:bg-sky-950/40 dark:text-sky-200";
  return "bg-wine-soft text-wine";
}

export function CalendarPage() {
  const { identityKey } = useApp();
  const [view, setView] = useState<View>("list");
  const [scope, setScope] = useState<Scope>("firm");
  const [matterId, setMatterId] = useState("");
  const [status, setStatus] = useState<(typeof STATUS)[number]>("open");
  const [cursor, setCursor] = useState(() => new Date());
  const [open, setOpen] = useState<CalItem | null>(null);
  const [creating, setCreating] = useState<"event" | "deadline" | null>(null);
  const [subscribing, setSubscribing] = useState(false);
  const matters = useMatters({ status: "Open", limit: 200 });

  // The range the view needs: a wide window for the list, the visible grid otherwise.
  const range = useMemo(() => {
    const today = new Date();
    if (view === "list") return { from: isoDay(addDays(today, -60)), to: isoDay(addDays(today, 330)) };
    if (view === "week") {
      const monday = addDays(cursor, -((cursor.getDay() + 6) % 7));
      return { from: isoDay(monday), to: isoDay(addDays(monday, 6)) };
    }
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const start = addDays(first, -((first.getDay() + 6) % 7));
    return { from: isoDay(start), to: isoDay(addDays(start, 41)) };
  }, [view, cursor]);

  const enabled = Boolean(identityKey) && (scope !== "matter" || Boolean(matterId));
  const cal = useQuery({
    queryKey: [identityKey, "calendar", scope, matterId, range.from, range.to],
    queryFn: () => apiFetch<{ items: CalItem[] }>(
      `/api/calendar?from=${range.from}&to=${range.to}&scope=${scope}${scope === "matter" ? `&matter_id=${encodeURIComponent(matterId)}` : ""}`,
    ).then((r) => r.items),
    enabled,
  });
  const rows = useMemo(
    () => (cal.data ?? []).filter((it) => status === "all" || it.status === status),
    [cal.data, status],
  );
  const query = { ...cal, data: cal.data ? rows : undefined } as typeof cal;
  const unconfirmed = rows.filter((r) => r.confirmed === false).length;

  return (
    <div className="space-y-6">
      <PageHeader
        compact
        title="Calendar"
        count={cal.data ? `${rows.length} ${rows.length === 1 ? "item" : "items"}` : undefined}
        subtitle="Court dates, deadlines and meetings across the matters you can access."
        actions={
          <>
            <Action icon="event" onClick={() => setCreating("event")} testId="calendar-new-event">New event</Action>
            <Action icon="gavel" onClick={() => setCreating("deadline")} testId="calendar-new-deadline">New court date</Action>
            <Action icon="rss_feed" onClick={() => setSubscribing(true)} testId="calendar-subscribe">Subscribe</Action>
          </>
        }
      />

      <div className="flex flex-wrap items-center gap-2">
        <Segmented value={view} onChange={setView} options={["list", "week", "month"]} testId="calendar-view" />
        <Segmented value={scope} onChange={setScope} options={SCOPES.map((s) => s.key)} labels={Object.fromEntries(SCOPES.map((s) => [s.key, s.label]))}
          testId="calendar-scope" />
        {scope === "matter" && (
          <select className="rounded-md border border-border bg-card px-2 py-1.5 text-xs" value={matterId} onChange={(e) => setMatterId(e.target.value)}
            aria-label="Matter" data-testid="calendar-matter">
            <option value="">Choose a matter…</option>
            {(matters.data?.items ?? []).map((m) => <option key={m.matter_id} value={m.matter_id}>{m.matter_code} — {m.title}</option>)}
          </select>
        )}
        <div className="ml-2 flex gap-1.5">
          {STATUS.map((s) => (
            <button key={s} type="button" onClick={() => setStatus(s)}
              className={cn("rounded-full border px-3 py-1.5 text-xs font-medium capitalize transition-colors",
                status === s ? "border-wine bg-wine-soft text-wine" : "border-border text-muted-foreground hover:bg-secondary")}>
              {s}
            </button>
          ))}
        </div>
        {unconfirmed > 0 && (
          <span className="ml-auto rounded-full bg-amber-100 px-2.5 py-1 text-xs text-amber-900" data-testid="calendar-unconfirmed">
            {unconfirmed} court {unconfirmed === 1 ? "date" : "dates"} awaiting confirmation
          </span>
        )}
      </div>

      {scope === "matter" && !matterId ? (
        <EmptyState icon="gavel" title="Choose a matter" />
      ) : (
        <QueryState query={query} isEmpty={(r) => r.length === 0 && view === "list"}
          empty={<EmptyState icon="event" title="Nothing here" description="Nothing matches this view within your access scope." />}>
          {(items) =>
            view === "list" ? <ListView rows={items} onOpen={setOpen} /> :
            view === "week" ? <WeekView rows={items} cursor={cursor} setCursor={setCursor} onOpen={setOpen} /> :
            <MonthGrid rows={items} cursor={cursor} setCursor={setCursor} onOpen={setOpen} />
          }
        </QueryState>
      )}

      {open && <ItemDialog item={open} onClose={() => setOpen(null)} />}
      {creating && <CreateDialog kind={creating} onClose={() => setCreating(null)} defaultMatter={scope === "matter" ? matterId : ""} />}
      {subscribing && <SubscribeDialog onClose={() => setSubscribing(false)} />}
    </div>
  );
}

function Segmented<T extends string>({ value, onChange, options, labels, testId }: {
  value: T; onChange: (v: T) => void; options: T[]; labels?: Record<string, string>; testId: string;
}) {
  return (
    <div className="inline-flex overflow-hidden rounded-md border border-border" role="tablist">
      {options.map((o) => (
        <button key={o} type="button" role="tab" aria-selected={value === o} onClick={() => onChange(o)} data-testid={`${testId}-${o}`}
          className={cn("px-3 py-1.5 text-xs font-medium capitalize transition-colors",
            value === o ? "bg-wine-soft text-wine" : "text-muted-foreground hover:bg-secondary")}>
          {labels?.[o] ?? o}
        </button>
      ))}
    </div>
  );
}

function Badges({ it }: { it: CalItem }) {
  return (
    <>
      {it.confirmed === false && <span className="ml-1.5 rounded bg-amber-100 px-1 text-[10px] font-semibold uppercase text-amber-900" data-testid="badge-unconfirmed">unconfirmed</span>}
      {it.restricted && <Icon name="shield_lock" className="ml-1 align-middle text-muted-foreground" style={{ fontSize: 13 }} />}
    </>
  );
}

function ListView({ rows, onOpen }: { rows: CalItem[]; onOpen: (it: CalItem) => void }) {
  return (
    <DataTable
      testId="deadlines-table"
      rows={rows}
      getRowKey={(d) => d.id}
      onRowClick={onOpen}
      columns={[
        {
          key: "due",
          header: "When",
          width: 160,
          render: (d) => (
            <div>
              <div className={cn("text-sm tabular-nums", isOverdue(d) ? "text-destructive" : "text-foreground")}>
                {formatDate(dayOf(d))} {timeOf(d) && <span className="text-muted-foreground">{timeOf(d)}</span>}
              </div>
              <div className="text-xs text-muted-foreground">{dueLabel(dayOf(d))}</div>
            </div>
          ),
        },
        {
          key: "title",
          header: "What",
          render: (d) => (
            <div>
              <div className="text-foreground">{d.title}<Badges it={d} /></div>
              <div className="text-xs capitalize text-muted-foreground">{d.kind.replace(/_/g, " ")}{d.source === "event" ? " · event" : ""}</div>
            </div>
          ),
        },
        {
          key: "matter",
          secondary: true,
          header: "Matter",
          render: (d) => d.matter_id ? (
            <div>
              <div className="font-mono-id text-xs text-muted-foreground">{d.matter_code}</div>
              <div className="text-sm">{d.matter_title}</div>
            </div>
          ) : <span className="text-sm text-muted-foreground">Personal</span>,
        },
        { key: "court", secondary: true, header: "Where", render: (d) => <span className="text-sm text-muted-foreground">{d.location || "—"}</span> },
        { key: "owner", secondary: true, header: "Owner", render: (d) => <span className="text-sm">{d.owner_name || "—"}</span> },
        { key: "status", header: "Status", align: "right", render: (d) => <StatusLabel status={d.status === "done" ? "Resolved" : "Open"} /> },
      ]}
    />
  );
}

const WEEKDAYS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

function Nav({ label, onPrev, onNext, onToday }: { label: string; onPrev: () => void; onNext: () => void; onToday: () => void }) {
  return (
    <div className="mb-3 flex items-center justify-between">
      <h2 className="font-display text-2xl text-ink">{label}</h2>
      <div className="flex gap-1">
        <Button variant="outline" size="sm" onClick={onToday}>Today</Button>
        <button type="button" aria-label="Previous" onClick={onPrev} className="rounded-md p-1.5 hover:bg-secondary"><Icon name="chevron_left" /></button>
        <button type="button" aria-label="Next" onClick={onNext} className="rounded-md p-1.5 hover:bg-secondary"><Icon name="chevron_right" /></button>
      </div>
    </div>
  );
}

function Chip({ it, onOpen }: { it: CalItem; onOpen: (it: CalItem) => void }) {
  return (
    <button type="button" onClick={() => onOpen(it)} title={`${it.title}${it.matter_code ? ` · ${it.matter_code}` : ""}`}
      className={cn("block w-full truncate rounded px-1.5 py-0.5 text-left text-[11px]", tone(it))} data-testid="calendar-chip">
      {timeOf(it) && <span className="mr-1 tabular-nums">{timeOf(it)}</span>}
      {it.confirmed === false && "⚠ "}{it.title}
    </button>
  );
}

function byDay(rows: CalItem[]) {
  const m = new Map<string, CalItem[]>();
  for (const r of rows) m.set(dayOf(r), [...(m.get(dayOf(r)) ?? []), r]);
  return m;
}

function MonthGrid({ rows, cursor, setCursor, onOpen }: { rows: CalItem[]; cursor: Date; setCursor: (d: Date) => void; onOpen: (it: CalItem) => void }) {
  const days = useMemo(() => {
    const first = new Date(cursor.getFullYear(), cursor.getMonth(), 1);
    const start = addDays(first, -((first.getDay() + 6) % 7));
    return Array.from({ length: 42 }, (_, i) => addDays(start, i));
  }, [cursor]);
  const map = useMemo(() => byDay(rows), [rows]);
  const today = isoDay(new Date());
  return (
    <div data-testid="calendar-month">
      <Nav label={cursor.toLocaleDateString(undefined, { month: "long", year: "numeric" })}
        onPrev={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() - 1, 1))}
        onNext={() => setCursor(new Date(cursor.getFullYear(), cursor.getMonth() + 1, 1))} onToday={() => setCursor(new Date())} />
      <div className="grid grid-cols-7 border-l border-t border-border text-sm">
        {WEEKDAYS.map((w) => <div key={w} className="meta-label border-b border-r border-border px-2 py-1.5 text-[10px]">{w}</div>)}
        {days.map((d) => {
          const key = isoDay(d);
          return (
            <div key={key} className={cn("min-h-[92px] border-b border-r border-border p-1.5", d.getMonth() !== cursor.getMonth() && "bg-secondary/40 text-muted-foreground")}>
              <div className={cn("mb-1 font-mono-id text-xs", key === today && "inline-block rounded bg-wine px-1 text-primary-foreground")}>{d.getDate()}</div>
              <div className="space-y-1">{(map.get(key) ?? []).map((it) => <Chip key={it.id} it={it} onOpen={onOpen} />)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function WeekView({ rows, cursor, setCursor, onOpen }: { rows: CalItem[]; cursor: Date; setCursor: (d: Date) => void; onOpen: (it: CalItem) => void }) {
  const monday = addDays(cursor, -((cursor.getDay() + 6) % 7));
  const days = Array.from({ length: 7 }, (_, i) => addDays(monday, i));
  const map = byDay(rows);
  const today = isoDay(new Date());
  return (
    <div data-testid="calendar-week">
      <Nav label={`Week of ${monday.toLocaleDateString(undefined, { day: "numeric", month: "long", year: "numeric" })}`}
        onPrev={() => setCursor(addDays(cursor, -7))} onNext={() => setCursor(addDays(cursor, 7))} onToday={() => setCursor(new Date())} />
      <div className="grid gap-2 md:grid-cols-7">
        {days.map((d, i) => {
          const key = isoDay(d);
          const items = [...(map.get(key) ?? [])].sort((a, b) => Number(!a.all_day) - Number(!b.all_day) || a.start.localeCompare(b.start));
          return (
            <div key={key} className={cn("min-h-40 rounded-lg border border-border p-2", key === today && "border-wine")}>
              <div className="mb-2 text-xs text-muted-foreground">{WEEKDAYS[i]} <span className="font-mono-id text-foreground">{d.getDate()}</span></div>
              <div className="space-y-1">{items.map((it) => <Chip key={it.id} it={it} onOpen={onOpen} />)}</div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

function useCalWrite() {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (fn: () => Promise<unknown>, done: string) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
      await queryClient.invalidateQueries({ queryKey: [identityKey, "calendar"] });
      await queryClient.invalidateQueries({ queryKey: [identityKey, "my-work"] });
      toast(done);
      return true;
    } catch (err) {
      setError(firmError(err));
      return false;
    } finally {
      setBusy(false);
    }
  };
  return { run, busy, error };
}

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) });

function ItemDialog({ item, onClose }: { item: CalItem; onClose: () => void }) {
  const navigate = useNavigate();
  const { me } = useApp();
  const { run, busy, error } = useCalWrite();
  const [date, setDate] = useState(item.start.slice(0, 10));
  const isDeadline = item.source === "deadline";
  const base = isDeadline ? `/api/calendar/deadlines/${encodeURIComponent(item.id)}` : `/api/calendar/events/${encodeURIComponent(item.id)}`;
  const mayConfirm = isDeadline && item.confirmed === false && item.can_edit && me?.member_id !== item.owner_id && me?.member_id !== item.created_by;
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="calendar-item">
        <DialogHeader>
          <DialogTitle>{item.title}<Badges it={item} /></DialogTitle>
          <DialogDescription>
            {formatDate(dayOf(item))} {timeOf(item)} · <span className="capitalize">{item.kind.replace(/_/g, " ")}</span>
            {item.location ? ` · ${item.location}` : ""}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          {item.matter_id && (
            <button type="button" className="text-left text-wine underline" onClick={() => navigate(`/matters/${item.matter_id}`)}>
              {item.matter_code} — {item.matter_title}
            </button>
          )}
          {item.notes && <p className="whitespace-pre-wrap text-muted-foreground">{item.notes}</p>}
          <p className="text-xs text-muted-foreground">
            {item.owner_name ? `Owner: ${item.owner_name}. ` : ""}
            {item.confirmed === true && item.confirmed_by ? `Confirmed by ${item.confirmed_by}.` : ""}
            {item.confirmed === false ? "A second lawyer has not yet checked this date against the order or rules." : ""}
          </p>
          {item.can_edit && (
            <div className="flex flex-wrap items-center gap-2 border-t border-border pt-3">
              {mayConfirm && (
                <Button size="sm" disabled={busy} data-testid="calendar-confirm"
                  onClick={() => void run(() => apiFetch(`${base}/confirm`, json("POST")), "Court date confirmed").then((ok) => ok && onClose())}>
                  Confirm date
                </Button>
              )}
              {isDeadline && (
                <>
                  <input type="date" className="rounded border border-border bg-background px-1 py-0.5" value={date} onChange={(e) => setDate(e.target.value)}
                    aria-label="Due date" />
                  <Button size="sm" variant="outline" disabled={busy || date === item.start.slice(0, 10)}
                    onClick={() => void run(() => apiFetch(base, json("PATCH", { due_date: date, row_version: item.row_version })), "Date moved").then((ok) => ok && onClose())}>
                    Move
                  </Button>
                  <Button size="sm" variant="outline" disabled={busy}
                    onClick={() => void run(() => apiFetch(base, json("PATCH", { status: item.status === "done" ? "open" : "done" })),
                      item.status === "done" ? "Reopened" : "Marked done").then((ok) => ok && onClose())}>
                    {item.status === "done" ? "Reopen" : "Mark done"}
                  </Button>
                </>
              )}
              {!isDeadline && (
                <Button size="sm" variant="outline" className="text-destructive" disabled={busy}
                  onClick={() => void run(() => apiFetch(base, json("DELETE")), "Event deleted").then((ok) => ok && onClose())}>
                  Delete
                </Button>
              )}
            </div>
          )}
          {error && <p className="text-destructive" data-testid="form-error">{error}</p>}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function CreateDialog({ kind, onClose, defaultMatter }: { kind: "event" | "deadline"; onClose: () => void; defaultMatter: string }) {
  const matters = useMatters({ status: "Open", limit: 200 });
  const people = usePeople();
  const { run, busy, error } = useCalWrite();
  const [title, setTitle] = useState("");
  const [matterId, setMatterId] = useState(defaultMatter);
  const [day, setDay] = useState(isoDay(addDays(new Date(), 1)));
  const [start, setStart] = useState("10:00");
  const [end, setEnd] = useState("11:00");
  const [allDay, setAllDay] = useState(false);
  const [type, setType] = useState(kind === "event" ? "meeting" : "filing");
  const [location, setLocation] = useState("");
  const [attendees, setAttendees] = useState<string[]>([]);
  const submit = async () => {
    const ok = kind === "event"
      ? await run(() => apiFetch("/api/calendar/events", json("POST", {
          title, kind: type, matter_id: matterId || undefined, all_day: allDay, location, attendees,
          starts_at: allDay ? `${day}T00:00:00` : new Date(`${day}T${start}`).toISOString(),
          ends_at: allDay ? `${day}T23:59:00` : new Date(`${day}T${end}`).toISOString(),
        })), "Event added")
      : await run(() => apiFetch("/api/calendar/deadlines", json("POST", {
          title, kind: type, matter_id: matterId, due_date: day, court: location || undefined,
        })), "Court date added — a second lawyer needs to confirm it");
    if (ok) onClose();
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-md" data-testid="calendar-create">
        <DialogHeader>
          <DialogTitle>{kind === "event" ? "New event" : "New court date"}</DialogTitle>
          {kind === "deadline" && <DialogDescription>Hearing, filing and limitation dates stay “unconfirmed” until a second lawyer checks them.</DialogDescription>}
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <input className={inputCls} placeholder="Title" value={title} onChange={(e) => setTitle(e.target.value)} data-testid="calendar-create-title" />
          <select className={inputCls} value={matterId} onChange={(e) => setMatterId(e.target.value)} aria-label="Matter" data-testid="calendar-create-matter">
            <option value="">{kind === "event" ? "Personal (no matter)" : "Choose a matter…"}</option>
            {(matters.data?.items ?? []).map((m) => <option key={m.matter_id} value={m.matter_id}>{m.matter_code} — {m.title}</option>)}
          </select>
          <div className="grid grid-cols-2 gap-2">
            <select className={inputCls} value={type} onChange={(e) => setType(e.target.value)} aria-label="Kind">
              {(kind === "event" ? EVENT_KINDS : DEADLINE_KINDS).map((k) => <option key={k} value={k}>{k.replace(/_/g, " ")}</option>)}
            </select>
            <input type="date" className={inputCls} value={day} onChange={(e) => setDay(e.target.value)} aria-label="Date" data-testid="calendar-create-date" />
          </div>
          {kind === "event" && (
            <>
              <label className="flex items-center gap-2"><input type="checkbox" checked={allDay} onChange={(e) => setAllDay(e.target.checked)} /> All day</label>
              {!allDay && (
                <div className="grid grid-cols-2 gap-2">
                  <input type="time" className={inputCls} value={start} onChange={(e) => setStart(e.target.value)} aria-label="Starts" />
                  <input type="time" className={inputCls} value={end} onChange={(e) => setEnd(e.target.value)} aria-label="Ends" />
                </div>
              )}
              <select multiple className={`${inputCls} h-24`} value={attendees} aria-label="Attendees"
                onChange={(e) => setAttendees([...e.target.selectedOptions].map((o) => o.value))}>
                {(people.data ?? []).map((p) => <option key={p.member_id} value={p.member_id}>{p.name}</option>)}
              </select>
            </>
          )}
          <input className={inputCls} placeholder={kind === "event" ? "Location (optional)" : "Court / forum (optional)"} value={location}
            onChange={(e) => setLocation(e.target.value)} />
          {error && <p className="text-destructive" data-testid="form-error">{error}</p>}
          <div className="flex justify-end gap-2">
            <Button variant="outline" onClick={onClose}>Cancel</Button>
            <Button disabled={busy || !title.trim() || (kind === "deadline" && !matterId)} onClick={() => void submit()} data-testid="calendar-create-save">Add</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SubscribeDialog({ onClose }: { onClose: () => void }) {
  const { identityKey, toast } = useApp();
  const queryClient = useQueryClient();
  const key = [identityKey, "calendar-feed"];
  const status = useQuery({ queryKey: key, queryFn: () => apiFetch<{ active: boolean; last_used_at?: string | null }>("/api/calendar/feed") });
  const [url, setUrl] = useState<string | null>(null);
  const [showRestricted, setShowRestricted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const make = async () => {
    setError(null);
    try {
      const out = await apiFetch<{ url: string }>("/api/calendar/feed", json("POST", { show_restricted: showRestricted }));
      setUrl(out.url);
      await queryClient.invalidateQueries({ queryKey: key });
    } catch (err) {
      setError(firmError(err));
    }
  };
  const revoke = async () => {
    await apiFetch("/api/calendar/feed", json("DELETE"));
    setUrl(null);
    await queryClient.invalidateQueries({ queryKey: key });
    toast("Calendar feed turned off");
  };
  return (
    <Dialog open onOpenChange={(o) => !o && onClose()}>
      <DialogContent className="max-w-lg" data-testid="calendar-subscribe-dialog">
        <DialogHeader>
          <DialogTitle>Subscribe in Outlook, Apple or Google Calendar</DialogTitle>
          <DialogDescription>
            A private link to your own dates (read-only). Anyone with the link can read it — treat it like a password; make a new
            one or turn it off at any time.
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-3 text-sm">
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={showRestricted} onChange={(e) => setShowRestricted(e.target.checked)} className="mt-0.5" />
            <span>Show titles of restricted matters (otherwise they appear as “Restricted matter”)</span>
          </label>
          {url && (
            <div className="space-y-1">
              <input readOnly className={`${inputCls} font-mono text-xs`} value={url} onFocus={(e) => e.target.select()} data-testid="calendar-feed-url" />
              <p className="text-xs text-muted-foreground">Copy it now — it is not shown again.</p>
            </div>
          )}
          {!url && status.data?.active && <p className="text-xs text-muted-foreground">A feed is active{status.data.last_used_at ? `, last read ${formatDate(status.data.last_used_at)}` : ""}.</p>}
          {error && <p className="text-destructive">{error}</p>}
          <div className="flex justify-end gap-2">
            {status.data?.active && <Button variant="outline" className="text-destructive" onClick={() => void revoke()}>Turn off</Button>}
            <Button onClick={() => void make()} data-testid="calendar-feed-create">{status.data?.active ? "Make a new link" : "Create link"}</Button>
          </div>
        </div>
      </DialogContent>
    </Dialog>
  );
}
