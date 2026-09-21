import { NavLink, Outlet, useLocation, useNavigate } from 'react-router-dom'
import { useEffect, useMemo, useState } from 'react'
import { useApp } from '../context/AppContext'
import { PERSONAS } from '../api/types'
import { CommandPalette } from '../components/CommandPalette'

type NavItem = {
  to: string
  label: string
  icon: string
  end?: boolean
  badge?: string
}

const WORKSPACE_NAV: NavItem[] = [
  { to: '/', label: 'Overview', icon: 'home', end: true },
  { to: '/ask', label: 'Ask FirmOS', icon: 'auto_awesome' },
  { to: '/chat', label: 'Chat', icon: 'forum' },
  { to: '/matters', label: 'Matters', icon: 'folder_open' },
  { to: '/documents', label: 'Documents', icon: 'description' },
  { to: '/knowledge', label: 'Knowledge', icon: 'auto_stories' },
]

const MANAGE_NAV: NavItem[] = [
  { to: '/clients', label: 'Clients', icon: 'corporate_fare' },
  { to: '/people', label: 'People', icon: 'group' },
  { to: '/activity', label: 'Activity', icon: 'schedule' },
  { to: '/approvals', label: 'Approvals', icon: 'fact_check', badge: '3' },
  { to: '/settings', label: 'Settings', icon: 'settings' },
]

function NavEntries({ items }: { items: NavItem[] }) {
  return (
    <nav className="legal-nav">
      {items.map((item) => (
        <NavLink
          key={item.to}
          to={item.to}
          end={item.end}
          className={({ isActive }) => `nav-link${isActive ? ' is-active' : ''}`}
        >
          <span className="material-symbols-outlined">{item.icon}</span>
          <span>{item.label}</span>
          {item.badge ? <em>{item.badge}</em> : null}
        </NavLink>
      ))}
    </nav>
  )
}

function crumbLabel(pathname: string) {
  if (pathname === '/' || pathname === '') return 'Overview'
  const seg = pathname.split('/').filter(Boolean)[0]
  const map: Record<string, string> = {
    ask: 'Ask FirmOS',
    chat: 'Chat',
    matters: 'Matters',
    documents: 'Documents',
    knowledge: 'Knowledge',
    clients: 'Clients',
    people: 'People',
    activity: 'Activity',
    approvals: 'Approvals',
    settings: 'Settings',
    support: 'Support',
    teams: 'Teams',
    tasks: 'Tasks',
  }
  return map[seg || ''] || 'Workspace'
}

export function AppShell() {
  const { persona, setPersona, loading, error, toasts, people } = useApp()
  const [paletteOpen, setPaletteOpen] = useState(false)
  const navigate = useNavigate()
  const location = useLocation()

  const personaMeta = useMemo(
    () => PERSONAS.find((p) => p.id === persona),
    [persona],
  )
  const person = people.find((p) => p.member_id === persona)
  const initials =
    (person?.name || personaMeta?.label || 'AM')
      .split(' ')
      .map((w) => w[0])
      .slice(0, 2)
      .join('')
      .toUpperCase() || 'AM'

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setPaletteOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="legal-app">
      <a className="skip-link" href="#workspace">
        Skip to workspace
      </a>

      <aside className="legal-sidebar" aria-label="Product navigation">
        <div className="sidebar-top">
          <button
            type="button"
            className="brand-lockup"
            onClick={() => navigate('/')}
          >
            <div className="app-mark" aria-hidden>
              F<span>.</span>
            </div>
            <span>FirmOS</span>
          </button>
        </div>

        <div className="firm-switcher">
          <span className="avatar avatar-ink">AC</span>
          <span>
            <b>Apex Chambers</b>
            <small>Firm workspace</small>
          </span>
          <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
            expand_more
          </span>
        </div>

        <p className="nav-label">Workspace</p>
        <NavEntries items={WORKSPACE_NAV} />
        <p className="nav-label nav-label-lower">Manage</p>
        <NavEntries items={MANAGE_NAV} />

        <div className="sidebar-bottom">
          <NavLink to="/support" className="help-link">
            <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
              help
            </span>
            Help & support
          </NavLink>
          <div className="user-block">
            <span className="avatar">{initials}</span>
            <span>
              <b>{person?.name || personaMeta?.label || 'Counsel'}</b>
              <small>{person?.role || 'Member'}</small>
            </span>
            <select
              className="persona-inline"
              value={persona}
              aria-label="Switch persona"
              onChange={(e) => setPersona(e.target.value)}
            >
              {PERSONAS.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.label}
                </option>
              ))}
            </select>
          </div>
        </div>
      </aside>

      <div className="legal-main">
        <header className="legal-header">
          <button
            type="button"
            className="global-search"
            onClick={() => setPaletteOpen(true)}
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              search
            </span>
            <span>Search matters, documents, people…</span>
            <kbd>⌘K</kbd>
          </button>
          <div className="header-actions">
            <button type="button" className="icon-button" aria-label="Notifications">
              <span className="material-symbols-outlined" style={{ fontSize: 19 }}>
                notifications
              </span>
              <i />
            </button>
            <button
              type="button"
              className="header-avatar"
              aria-label="Account"
              onClick={() => setPaletteOpen(true)}
            >
              <span className="avatar">{initials}</span>
            </button>
          </div>
        </header>

        <div id="workspace" className="legal-workspace" tabIndex={-1}>
          <div className="crumb">
            <span>Workspace</span>
            <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
              chevron_right
            </span>
            <b>{crumbLabel(location.pathname)}</b>
          </div>

          {error ? (
            <div>
              <h1 className="page-title">Unable to load firm data</h1>
              <p className="lede">{error}</p>
              <button
                type="button"
                className="button button-primary"
                onClick={() => navigate(0)}
              >
                Retry
              </button>
            </div>
          ) : loading ? (
            <div className="empty">
              <div className="empty-mark">FirmOS</div>
              Loading firm memory…
            </div>
          ) : (
            <Outlet />
          )}
        </div>
      </div>

      {paletteOpen ? (
        <CommandPalette onClose={() => setPaletteOpen(false)} />
      ) : null}

      <div className="toast-host" aria-live="polite">
        {toasts.map((t, i) => (
          <div key={`${t}-${i}`} className="toast">
            {t}
          </div>
        ))}
      </div>
    </div>
  )
}
