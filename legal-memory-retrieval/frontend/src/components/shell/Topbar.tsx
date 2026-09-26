import { Fragment, useCallback, useSyncExternalStore } from "react";
import { Link, useLocation } from "react-router-dom";
import { useQueryClient } from "@tanstack/react-query";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Icon } from "@/components/common/primitives";
import { PersonAvatar } from "@/components/common/EntityLink";
import { initials, useApp } from "@/context/AppContext";
import { useTheme, type Theme } from "@/lib/theme";

const LABELS: Record<string, string> = {
  ask: "Ask the Firm",
  chat: "Assistant",
  assistant: "Assistant",
  matters: "Matters",
  clients: "Clients",
  documents: "Documents",
  people: "People",
  calendar: "Calendar",
  arguments: "Arguments",
  settings: "Settings",
  admin: "Admin",
  history: "Draft evolution",
};

const RECORD_KEYS: Record<string, string> = { matters: "matter", documents: "document", clients: "client", people: "person" };

/** Title of a record the current page has already loaded (no extra request). */
function useRecordTitle(section: string | undefined, id: string | undefined): string | undefined {
  const queryClient = useQueryClient();
  const { identityKey } = useApp();
  const key = section ? RECORD_KEYS[section] : undefined;
  const read = useCallback((): string | undefined => {
    if (!key || !id) return undefined;
    for (const [, data] of queryClient.getQueriesData<Record<string, unknown>>({ queryKey: [identityKey, key, id] })) {
      if (!data || typeof data !== "object") continue;
      const rec = (data.matter ?? data.person ?? data) as Record<string, unknown>;
      const title = rec.title ?? rec.name;
      if (typeof title === "string") return title;
    }
    return undefined;
  }, [queryClient, identityKey, key, id]);
  // Re-render when the page's query resolves.
  return useSyncExternalStore((cb) => queryClient.getQueryCache().subscribe(cb), read, read);
}

function Crumbs() {
  const { pathname } = useLocation();
  const { firm } = useApp();
  const segs = pathname.split("/").filter(Boolean);
  const recordTitle = useRecordTitle(segs[0], segs[1]);
  const crumbs: { label: string; to: string }[] = [{ label: firm?.name || "Home", to: "/" }];
  let acc = "";
  segs.forEach((s, i) => {
    acc += `/${s}`;
    const label = i === 1 && recordTitle ? recordTitle : LABELS[s] || decodeURIComponent(s);
    crumbs.push({ label, to: acc });
  });
  return (
    <nav className="flex items-center gap-1.5 text-sm" aria-label="Breadcrumb">
      {crumbs.map((c, i) => (
        <Fragment key={c.to}>
          {i > 0 && <Icon name="chevron_right" className="text-muted-foreground" style={{ fontSize: 16 }} />}
          {i === crumbs.length - 1 ? (
            <span className="max-w-[320px] truncate font-medium text-foreground">{c.label}</span>
          ) : (
            <Link to={c.to} className="text-muted-foreground transition-colors hover:text-foreground">
              {c.label}
            </Link>
          )}
        </Fragment>
      ))}
    </nav>
  );
}

const THEMES: { value: Theme; label: string; icon: string }[] = [
  { value: "light", label: "Light", icon: "light_mode" },
  { value: "dark", label: "Dark", icon: "dark_mode" },
  { value: "system", label: "System", icon: "contrast" },
];

function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  const current = THEMES.find((t) => t.value === theme) ?? THEMES[2];
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-secondary hover:text-foreground"
          aria-label={`Theme: ${current.label}`}
          data-testid="theme-menu"
        >
          <Icon name={current.icon} style={{ fontSize: 20 }} />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-40">
        {THEMES.map((t) => (
          <DropdownMenuItem
            key={t.value}
            onClick={() => setTheme(t.value)}
            className={theme === t.value ? "bg-wine-soft text-wine" : undefined}
            data-testid={`theme-${t.value}`}
          >
            <Icon name={t.icon} className="mr-2" style={{ fontSize: 18 }} />
            {t.label}
          </DropdownMenuItem>
        ))}
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function Topbar({
  onOpenCommand,
  onOpenSidebar,
  collapsed,
  onToggleCollapse,
}: {
  onOpenCommand: () => void;
  onOpenSidebar: () => void;
  collapsed: boolean;
  onToggleCollapse: () => void;
}) {
  const { me, personas, setPersona, authEnabled, signOut } = useApp();
  const name = me?.name ?? "—";

  return (
    <header className="flex h-[52px] shrink-0 items-center gap-3 border-b border-border bg-paper px-4" data-testid="topbar">
      <button
        type="button"
        onClick={onOpenSidebar}
        className="text-muted-foreground hover:text-foreground lg:hidden"
        aria-label="Open navigation"
        data-testid="mobile-nav-toggle"
      >
        <Icon name="menu" />
      </button>
      <button
        type="button"
        onClick={onToggleCollapse}
        className="hidden text-muted-foreground hover:text-foreground lg:block"
        aria-label="Collapse navigation"
        data-testid="collapse-toggle"
      >
        <Icon name={collapsed ? "menu_open" : "menu"} />
      </button>

      <div className="hidden min-w-0 flex-1 md:block">
        <Crumbs />
      </div>

      <button
        type="button"
        onClick={onOpenCommand}
        data-testid="open-command"
        className="flex min-w-0 flex-1 items-center gap-2 rounded-md border border-border bg-card px-3 py-1.5 text-sm text-muted-foreground transition-colors hover:border-wine/40 md:max-w-sm md:flex-none"
      >
        <Icon name="search" style={{ fontSize: 18 }} />
        <span className="flex-1 text-left">Search Precentis…</span>
        <kbd className="hidden rounded border border-border bg-secondary px-1.5 py-0.5 font-mono-id text-[10px] text-muted-foreground sm:inline">
          ⌘K
        </kbd>
      </button>

      <div className="ml-auto flex items-center gap-1">
        <ThemeMenu />
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <button
              type="button"
              className="ml-1 flex items-center gap-2 rounded-md py-1 pl-1 pr-2 transition-colors hover:bg-secondary"
              data-testid="user-menu"
            >
              <PersonAvatar person={{ name, initials: initials(name) }} size={30} />
              <span className="hidden text-left leading-tight sm:block">
                <span className="block text-sm font-semibold text-foreground">{name}</span>
                <span className="block max-w-[160px] truncate text-[11px] text-muted-foreground">
                  {[me?.role, me?.office].filter(Boolean).join(" · ")}
                </span>
              </span>
              <Icon name="expand_more" className="text-muted-foreground" style={{ fontSize: 18 }} />
            </button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="max-h-[70vh] w-72 overflow-y-auto">
            {!authEnabled && personas.length > 0 && (
              <>
                <DropdownMenuLabel>
                  Viewing as
                  <div className="mt-1 text-xs font-normal text-muted-foreground">
                    Development mode — pick a member to see their access scope
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                {personas.map((p) => (
                  <DropdownMenuItem
                    key={p.member_id}
                    onClick={() => setPersona(p.member_id)}
                    className={me?.member_id === p.member_id ? "bg-wine-soft text-wine" : undefined}
                    data-testid={`persona-${p.member_id}`}
                  >
                    <span className="flex-1">{p.name}</span>
                    <span className="text-xs text-muted-foreground">{p.role}</span>
                  </DropdownMenuItem>
                ))}
                <DropdownMenuSeparator />
              </>
            )}
            {me && (
              <DropdownMenuItem asChild>
                <Link to={`/people/${me.member_id}`}>My profile</Link>
              </DropdownMenuItem>
            )}
            <DropdownMenuItem asChild>
              <Link to="/settings">Settings</Link>
            </DropdownMenuItem>
            {authEnabled && (
              <DropdownMenuItem onClick={signOut} data-testid="sign-out">
                Sign out
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
