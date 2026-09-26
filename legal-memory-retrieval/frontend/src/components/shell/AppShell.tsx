import { useCallback, useState, type FormEvent, type PointerEvent as ReactPointerEvent, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { Sheet, SheetContent } from "@/components/ui/sheet";
import { Toaster } from "@/components/ui/sonner";
import { Sidebar } from "@/components/shell/Sidebar";
import { Topbar } from "@/components/shell/Topbar";
import { CommandPalette } from "@/components/shell/CommandPalette";
import { InspectorProvider } from "@/components/common/Inspector";
import { ErrorState, Icon } from "@/components/common/primitives";
import { cn } from "@/lib/utils";
import { useApp } from "@/context/AppContext";

export function AppShell({ children }: { children: ReactNode }) {
  const { boot } = useApp();
  if (boot.phase === "loading") return <Centered><p className="text-sm text-muted-foreground">Connecting to the firm…</p></Centered>;
  if (boot.phase === "error") return <BootError message={boot.message} />;
  if (boot.phase === "needs-key") return <SignIn error={boot.error} />;
  return <Shell>{children}</Shell>;
}

const SIDEBAR_KEY = "precentis.sidebarWidth";
const SIDEBAR_MIN = 220;
const SIDEBAR_MAX = 320;
const SIDEBAR_DEFAULT = 256;

function readWidth() {
  try {
    const w = Number(localStorage.getItem(SIDEBAR_KEY));
    return w >= SIDEBAR_MIN && w <= SIDEBAR_MAX ? w : SIDEBAR_DEFAULT;
  } catch {
    return SIDEBAR_DEFAULT;
  }
}

/** Sidebar width, resizable by dragging its edge; remembered per browser. */
function useSidebarWidth() {
  const [width, setWidth] = useState(readWidth);
  const save = (w: number) => {
    try {
      localStorage.setItem(SIDEBAR_KEY, String(w));
    } catch {
      // not persisted
    }
  };
  const startDrag = useCallback((e: ReactPointerEvent) => {
    e.preventDefault();
    const startX = e.clientX;
    const startW = readWidth();
    let current = startW;
    const move = (ev: PointerEvent) => {
      current = Math.min(SIDEBAR_MAX, Math.max(SIDEBAR_MIN, startW + ev.clientX - startX));
      setWidth(current);
    };
    const up = () => {
      save(current);
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", up);
      document.body.style.cursor = "";
    };
    document.body.style.cursor = "col-resize";
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", up);
  }, []);
  const reset = useCallback(() => {
    setWidth(SIDEBAR_DEFAULT);
    save(SIDEBAR_DEFAULT);
  }, []);
  return { width, startDrag, reset };
}

const BOTTOM_NAV = [
  { to: "/", icon: "home", label: "Home", end: true },
  { to: "/matters", icon: "gavel", label: "Matters" },
  { to: "/chat", icon: "chat", label: "Chat" },
  { to: "/documents", icon: "description", label: "Documents" },
  { to: "/settings", icon: "person", label: "Profile" },
];

function BottomNav() {
  return (
    <nav
      className="fixed inset-x-0 bottom-0 z-40 grid grid-cols-5 border-t border-border bg-paper pb-[env(safe-area-inset-bottom)] md:hidden"
      aria-label="Primary (mobile)"
      data-testid="bottom-nav"
    >
      {BOTTOM_NAV.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) =>
            cn("flex flex-col items-center gap-0.5 py-2 text-[10px] font-medium", isActive ? "text-wine" : "text-muted-foreground")
          }
        >
          <Icon name={item.icon} style={{ fontSize: 22 }} />
          {item.label}
        </NavLink>
      ))}
    </nav>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const [cmdOpen, setCmdOpen] = useState(false);
  const [mobileNav, setMobileNav] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const sidebar = useSidebarWidth();
  const { pathname } = useLocation();
  // Remount (and fade) per section, not per URL: moving within a section keeps state.
  const section = pathname.split("/")[1] ?? "";
  // Full-bleed workspaces: document viewer and chat (history + thread need the width).
  const fillFrame = /^\/documents\/[^/]+/.test(pathname) || pathname === "/chat" || pathname.startsWith("/chat/");

  return (
    <InspectorProvider>
      <div className="flex h-screen w-full overflow-hidden bg-background text-foreground">
        <aside
          className="relative hidden shrink-0 border-r border-border lg:block"
          style={{ width: collapsed ? 68 : sidebar.width }}
        >
          <Sidebar collapsed={collapsed} />
          {!collapsed && (
            <div
              role="separator"
              aria-orientation="vertical"
              aria-label="Resize sidebar (double-click to reset)"
              onPointerDown={sidebar.startDrag}
              onDoubleClick={sidebar.reset}
              className="absolute inset-y-0 -right-1 z-10 w-2 cursor-col-resize transition-colors hover:bg-wine/20"
              data-testid="sidebar-resize"
            />
          )}
        </aside>

        <Sheet open={mobileNav} onOpenChange={setMobileNav}>
          <SheetContent side="left" className="w-[256px] p-0">
            <Sidebar onNavigate={() => setMobileNav(false)} />
          </SheetContent>
        </Sheet>

        <div className="flex min-w-0 flex-1 flex-col">
          <Topbar
            onOpenCommand={() => setCmdOpen(true)}
            onOpenSidebar={() => setMobileNav(true)}
            collapsed={collapsed}
            onToggleCollapse={() => setCollapsed((c) => !c)}
          />
          <main
            key={section}
            className={cn(
              "flex min-h-0 flex-1 animate-fade",
              fillFrame ? "overflow-hidden pb-16 md:pb-0" : "overflow-y-auto pb-16 md:pb-0",
            )}
          >
            {fillFrame ? (
              <div className="flex h-full min-h-0 w-full flex-col overflow-hidden">{children}</div>
            ) : (
              <div className="mx-auto w-full max-w-[1180px] px-6 py-8 lg:px-10 lg:py-10">{children}</div>
            )}
          </main>
        </div>
      </div>

      <BottomNav />
      <CommandPalette open={cmdOpen} setOpen={setCmdOpen} />
      <Toaster position="bottom-right" />
    </InspectorProvider>
  );
}

function Centered({ children }: { children: ReactNode }) {
  return <div className="flex min-h-screen items-center justify-center bg-background px-6">{children}</div>;
}

function BootError({ message }: { message: string }) {
  const { retryBoot } = useApp();
  return (
    <Centered>
      <div className="w-full max-w-lg">
        <ErrorState title="The firm's API is not reachable" description={message} onRetry={retryBoot} />
      </div>
    </Centered>
  );
}

function SignIn({ error }: { error?: string }) {
  const { signIn, firm, authOptions } = useApp();
  const [key, setKey] = useState("");
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (!key.trim()) return;
    setBusy(true);
    await signIn(key.trim());
    setBusy(false);
  };

  // Firm sign-in returns to the page the lawyer was trying to open.
  const next = encodeURIComponent(window.location.pathname + window.location.search.replace(/[?&]signin=failed/, ""));

  return (
    <Centered>
      <div className="w-full max-w-sm space-y-6" data-testid="sign-in">
        <div>
          <div className="flex items-center gap-2.5">
            <div className="flex h-8 w-8 items-center justify-center rounded-md bg-wine text-primary-foreground">
              <span className="font-display text-lg leading-none">P</span>
            </div>
            <span className="font-display text-lg text-ink">Precentis</span>
          </div>
          <h1 className="mt-6 font-display text-3xl text-ink">Sign in</h1>
          {firm?.name && <p className="mt-2 text-sm text-muted-foreground">{firm.name}</p>}
        </div>

        {error && (
          <p className="rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm text-destructive" role="alert">
            {error}
          </p>
        )}

        {authOptions.oidc && (
          <a
            href={`/api/auth/login?next=${next}`}
            data-testid="sign-in-oidc"
            className="flex w-full items-center justify-center gap-2 rounded-md bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground transition-opacity hover:opacity-90"
          >
            <Icon name="login" style={{ fontSize: 18 }} /> Sign in with your firm account
          </a>
        )}

        {authOptions.apiKey && (
          <form onSubmit={submit} className="space-y-3">
            {authOptions.oidc && <div className="meta-label text-center">or, for development</div>}
            <input
              type="password"
              autoComplete="current-password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="API key"
              aria-label="API key"
              className="w-full rounded-md border border-border bg-card px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-wine/40"
            />
            <button
              type="submit"
              disabled={busy || !key.trim()}
              className="w-full rounded-md border border-border bg-card px-4 py-2 text-sm font-semibold transition-colors hover:bg-secondary disabled:opacity-50"
            >
              {busy ? "Checking…" : "Sign in with API key"}
            </button>
          </form>
        )}

        {!authOptions.oidc && !authOptions.apiKey && (
          <p className="text-sm text-muted-foreground">Sign-in is not configured on this server. Contact your administrator.</p>
        )}
      </div>
    </Centered>
  );
}
