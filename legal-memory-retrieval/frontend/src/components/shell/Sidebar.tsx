import { Link, NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/common/primitives";
import { usePinnedMatters, useRecentConversations } from "@/api/resources";
import { useApp } from "@/context/AppContext";
import { can, useMyAccess } from "@/api/access";

// Admin shows only for people who administer something (plan §5).
const ADMIN_PERMISSIONS = ["users.manage", "teams.manage", "roles.manage", "walls.manage", "audit.read"];

type NavItemConfig = { to: string; icon: string; label: string; end?: boolean; hint?: string };

// Navigation decided in docs/ui-roadmap/00_ROADMAP.md §5 (Q7). Research joins "Work"
// when its page ships (P7) — the sidebar only lists sections that exist.
export const NAV_GROUPS: { label: string; items: NavItemConfig[] }[] = [
  {
    label: "Work",
    items: [
      { to: "/", icon: "home", label: "Home", end: true },
      { to: "/chat", icon: "edit_note", label: "Assistant", hint: "Draft and review documents" },
      { to: "/ask", icon: "manage_search", label: "Ask the Firm", hint: "Find what the firm already knows" },
      { to: "/matters", icon: "gavel", label: "Matters" },
      { to: "/documents", icon: "description", label: "Documents" },
      { to: "/calendar", icon: "event", label: "Calendar" },
    ],
  },
  {
    label: "Knowledge",
    items: [
      { to: "/arguments", icon: "balance", label: "Arguments" },
      { to: "/clients", icon: "apartment", label: "Clients" },
      { to: "/people", icon: "groups", label: "People" },
    ],
  },
  {
    label: "Manage",
    items: [{ to: "/settings", icon: "settings", label: "Settings" }],
  },
];

function NavItem({ item, collapsed }: { item: NavItemConfig; collapsed?: boolean }) {
  return (
    <NavLink
      to={item.to}
      end={item.end}
      title={collapsed ? item.label : item.hint}
      data-testid={`nav-${item.label.replace(/[^a-z]/gi, "-").toLowerCase()}`}
      className={({ isActive }) =>
        cn(
          "group relative flex items-center gap-3 rounded-md py-2 pl-3 pr-2 text-sm transition-colors duration-150",
          collapsed && "justify-center px-0",
          isActive ? "bg-wine-soft font-semibold text-wine" : "text-foreground/75 hover:bg-secondary hover:text-foreground",
        )
      }
    >
      {({ isActive }) => (
        <>
          {isActive && <span className="absolute left-0 top-1/2 h-5 -translate-y-1/2 rounded-full bg-wine" style={{ width: 3 }} />}
          <Icon
            name={item.icon}
            style={{ fontSize: 20 }}
            className={cn(isActive ? "text-wine" : "text-muted-foreground group-hover:text-foreground")}
          />
          {!collapsed && (
            <span className="min-w-0">
              <span className="block truncate">{item.label}</span>
              {item.hint && (
                <span aria-hidden className="block truncate text-xs font-normal text-muted-foreground">
                  {item.hint}
                </span>
              )}
            </span>
          )}
        </>
      )}
    </NavLink>
  );
}

function ShortcutList({
  label,
  testId,
  items,
  shortScreenLimit,
}: {
  label: string;
  testId: string;
  items: { key: string; to: string; title: string; hint?: string; icon: string }[];
  /** On screens under 900px tall, hide items past this many. */
  shortScreenLimit?: number;
}) {
  const { pathname } = useLocation();
  if (items.length === 0) return null;
  return (
    <div className="mb-5" data-testid={testId}>
      <div className="meta-label px-3 pb-1.5 text-xs">{label}</div>
      <div className="space-y-0.5">
        {items.map((it, i) => (
          <Link
            key={it.key}
            to={it.to}
            title={it.title}
            className={cn(
              "flex items-center gap-2.5 rounded-md py-1.5 pl-3 pr-2 text-[13px] transition-colors",
              shortScreenLimit != null && i >= shortScreenLimit && "[@media(max-height:900px)]:hidden",
              pathname === it.to ? "bg-secondary text-foreground" : "text-foreground/70 hover:bg-secondary hover:text-foreground",
            )}
          >
            <Icon name={it.icon} className="text-muted-foreground" style={{ fontSize: 16 }} />
            <span className="min-w-0 flex-1 truncate">{it.title}</span>
            {it.hint && <span className="shrink-0 font-mono-id text-xs text-muted-foreground">{it.hint}</span>}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function Sidebar({ collapsed, onNavigate, onShortcuts }: { collapsed?: boolean; onNavigate?: () => void; onShortcuts?: () => void }) {
  const { firm } = useApp();
  const pinned = usePinnedMatters();
  const recent = useRecentConversations();
  const firmMeta = [firm?.descriptor, firm?.office].filter(Boolean).join(" · ");

  const me = useMyAccess();
  const showAdmin = ADMIN_PERMISSIONS.some((p) => can(me.data, p));
  const navGroups = NAV_GROUPS.map((g) =>
    g.label === "Manage" && showAdmin ? { ...g, items: [{ to: "/admin", icon: "admin_panel_settings", label: "Admin" }, ...g.items] } : g,
  );

  return (
    <nav className="flex h-full flex-col bg-paper" aria-label="Primary" data-testid="sidebar" onClick={onNavigate}>
      <Link to="/" className={cn("flex items-center gap-2.5 px-5 pb-4 pt-5", collapsed && "justify-center px-0")}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-wine text-primary-foreground">
          <span className="font-display text-lg leading-none">P</span>
        </div>
        {!collapsed && <div className="font-display text-lg text-ink">Precentis</div>}
      </Link>

      {!collapsed && firm?.name && (
        <div className="mx-3 mb-2 truncate px-3 text-[13px] font-semibold text-ink" title={firmMeta ? `${firm.name} · ${firmMeta}` : firm.name} data-testid="firm-identity">
          {firm.name}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 pb-6 pt-2">
        {navGroups.map((group) => (
          <div key={group.label} className="mb-5">
            {!collapsed && <div className="meta-label px-3 pb-1.5 text-xs">{group.label}</div>}
            <div className="space-y-0.5">
              {group.items.map((item) => (
                <NavItem key={item.to} item={item} collapsed={collapsed} />
              ))}
            </div>
          </div>
        ))}

        {!collapsed && (
          <>
            <ShortcutList
              label="Pinned matters"
              testId="sidebar-pinned"
              items={(pinned.data ?? []).slice(0, 6).map((m) => ({
                key: m.matter_id,
                to: `/matters/${m.matter_id}`,
                title: m.title,
                icon: m.restricted ? "lock" : "push_pin",
              }))}
            />
            <ShortcutList
              label="Recent conversations"
              testId="sidebar-recent"
              shortScreenLimit={3}
              items={(recent.data ?? []).slice(0, 5).map((s) => ({
                key: s.id,
                to: `/chat/${s.id}`,
                title: s.title || "Untitled conversation",
                icon: "chat_bubble",
              }))}
            />
            {(recent.data ?? []).length > 3 && (
              <Link
                to="/chat?history=open"
                className="-mt-4 mb-5 block rounded-md py-1.5 pl-3 text-[12px] font-medium text-wine hover:bg-secondary"
                data-testid="sidebar-all-conversations"
              >
                All conversations
              </Link>
            )}
          </>
        )}
      </div>

      {!collapsed && onShortcuts && (
        <div className="border-t border-border px-3 py-2">
          <button
            type="button"
            onClick={(e) => {
              e.stopPropagation();
              onShortcuts();
            }}
            data-testid="sidebar-shortcuts"
            className="flex w-full items-center gap-2.5 rounded-md py-1.5 pl-3 pr-2 text-[13px] text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          >
            <Icon name="keyboard" style={{ fontSize: 16 }} /> Keyboard shortcuts
          </button>
        </div>
      )}
    </nav>
  );
}
