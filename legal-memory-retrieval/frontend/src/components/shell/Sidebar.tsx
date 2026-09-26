import { Link, NavLink, useLocation } from "react-router-dom";
import { cn } from "@/lib/utils";
import { Icon } from "@/components/common/primitives";
import { usePinnedMatters, useRecentConversations } from "@/api/resources";
import { useApp } from "@/context/AppContext";

type NavItemConfig = { to: string; icon: string; label: string; end?: boolean };

// Navigation decided in docs/ui-roadmap/00_ROADMAP.md §5 (Q7). Research joins "Work"
// when its page ships (P7) — the sidebar only lists sections that exist.
export const NAV_GROUPS: { label: string; items: NavItemConfig[] }[] = [
  {
    label: "Work",
    items: [
      { to: "/", icon: "home", label: "Home", end: true },
      { to: "/chat", icon: "chat", label: "Chat" },
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
      title={collapsed ? item.label : undefined}
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
          {!collapsed && <span className="truncate">{item.label}</span>}
        </>
      )}
    </NavLink>
  );
}

function ShortcutList({
  label,
  testId,
  items,
}: {
  label: string;
  testId: string;
  items: { key: string; to: string; title: string; hint?: string; icon: string }[];
}) {
  const { pathname } = useLocation();
  if (items.length === 0) return null;
  return (
    <div className="mb-5" data-testid={testId}>
      <div className="meta-label px-3 pb-1.5 text-[10px]">{label}</div>
      <div className="space-y-0.5">
        {items.map((it) => (
          <Link
            key={it.key}
            to={it.to}
            title={it.title}
            className={cn(
              "flex items-center gap-2.5 rounded-md py-1.5 pl-3 pr-2 text-[13px] transition-colors",
              pathname === it.to ? "bg-secondary text-foreground" : "text-foreground/70 hover:bg-secondary hover:text-foreground",
            )}
          >
            <Icon name={it.icon} className="text-muted-foreground" style={{ fontSize: 16 }} />
            <span className="min-w-0 flex-1 truncate">{it.title}</span>
            {it.hint && <span className="shrink-0 font-mono-id text-[10px] text-muted-foreground">{it.hint}</span>}
          </Link>
        ))}
      </div>
    </div>
  );
}

export function Sidebar({ collapsed, onNavigate }: { collapsed?: boolean; onNavigate?: () => void }) {
  const { firm } = useApp();
  const pinned = usePinnedMatters();
  const recent = useRecentConversations();
  const firmMeta = [firm?.descriptor, firm?.office].filter(Boolean).join(" · ");

  return (
    <nav className="flex h-full flex-col bg-paper" aria-label="Primary" data-testid="sidebar" onClick={onNavigate}>
      <Link to="/" className={cn("flex items-center gap-2.5 px-5 pb-4 pt-5", collapsed && "justify-center px-0")}>
        <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md bg-wine text-primary-foreground">
          <span className="font-display text-lg leading-none">P</span>
        </div>
        {!collapsed && <div className="font-display text-lg text-ink">Precentis</div>}
      </Link>

      {!collapsed && firm?.name && (
        <div className="mx-3 mb-2 rounded-md border border-border bg-card px-3 py-2" data-testid="firm-identity">
          <span className="meta-label block text-[10px]">Workspace</span>
          <span className="block text-sm font-semibold text-ink">{firm.name}</span>
          {firmMeta && <span className="block text-[11px] text-muted-foreground">{firmMeta}</span>}
        </div>
      )}

      <div className="flex-1 overflow-y-auto px-3 pb-6 pt-2">
        {NAV_GROUPS.map((group) => (
          <div key={group.label} className="mb-5">
            {!collapsed && <div className="meta-label px-3 pb-1.5 text-[10px]">{group.label}</div>}
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
              items={(recent.data ?? []).slice(0, 5).map((s) => ({
                key: s.id,
                to: `/chat/${s.id}`,
                title: s.title || "Untitled conversation",
                icon: "chat_bubble",
              }))}
            />
          </>
        )}
      </div>

      {!collapsed && (
        <div className="border-t border-border px-5 py-3 text-[10px] leading-relaxed text-muted-foreground">
          <div className="flex items-center gap-1.5">
            <Icon name="shield" style={{ fontSize: 13 }} /> Firm-isolated knowledge
          </div>
          <div className="flex items-center gap-1.5">
            <Icon name="visibility_lock" style={{ fontSize: 13 }} /> Permission-aware retrieval
          </div>
        </div>
      )}
    </nav>
  );
}
