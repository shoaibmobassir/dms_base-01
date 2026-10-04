// One way to show dates across the app: "25 Aug 2026" (and "25 Aug 2026, 14:02").
// ISO strings stay in exports and tooltips.

function parse(value: string): Date {
  // A bare date ("2026-08-25") is a calendar day, not midnight UTC.
  return /^\d{4}-\d{2}-\d{2}$/.test(value) ? new Date(`${value}T00:00:00`) : new Date(value);
}

export function formatDate(value?: string | null, fallback = "—"): string {
  if (!value) return fallback;
  const d = parse(value);
  if (Number.isNaN(d.getTime())) return value;
  return d.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: "numeric" });
}

export function formatDateTime(value?: string | null, fallback = "—"): string {
  if (!value) return fallback;
  const d = parse(value);
  if (Number.isNaN(d.getTime())) return value;
  return `${formatDate(value)}, ${d.toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit" })}`;
}

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
