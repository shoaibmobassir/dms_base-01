import { useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function CommandPalette({ onClose }: { onClose: () => void }) {
  const { matters, documents, clients, projects, people } = useApp()
  const [q, setQ] = useState('')
  const [active, setActive] = useState(0)
  const navigate = useNavigate()

  const results = useMemo(() => {
    const query = q.trim().toLowerCase()
    const items: Array<{ kind: string; label: string; path: string }> = [
      { kind: 'Nav', label: 'Home', path: '/' },
      { kind: 'Nav', label: 'Chat Assistant', path: '/chat' },
      { kind: 'Nav', label: 'Ask FirmOS', path: '/ask' },
      { kind: 'Nav', label: 'Matters', path: '/matters' },
      { kind: 'Nav', label: 'Projects', path: '/projects' },
      { kind: 'Nav', label: 'Documents', path: '/documents' },
      { kind: 'Nav', label: 'Knowledge', path: '/knowledge' },
      { kind: 'Nav', label: 'Clients', path: '/clients' },
      { kind: 'Nav', label: 'People', path: '/people' },
      { kind: 'Nav', label: 'Activity', path: '/activity' },
      { kind: 'Nav', label: 'Tasks', path: '/tasks' },
      { kind: 'Nav', label: 'Architecture', path: '/architecture' },
    ]

    for (const m of matters.slice(0, 40)) {
      items.push({
        kind: 'Matter',
        label: `${m.matter_code || m.matter_id} — ${m.title}`,
        path: `/matters/${m.matter_id}`,
      })
    }
    for (const d of documents.slice(0, 40)) {
      items.push({
        kind: 'Document',
        label: `${d.document_id} — ${d.title}`,
        path: `/documents/${d.document_id}`,
      })
    }
    for (const c of clients.slice(0, 20)) {
      items.push({
        kind: 'Client',
        label: c.name,
        path: `/clients/${c.client_id}`,
      })
    }
    for (const p of projects.slice(0, 20)) {
      items.push({
        kind: 'Project',
        label: p.title,
        path: `/projects/${p.project_id}`,
      })
    }
    for (const person of people.slice(0, 20)) {
      items.push({
        kind: 'Person',
        label: `${person.name} — ${person.role || 'Member'}`,
        path: `/people/${person.member_id}`,
      })
    }

    if (!query) return items.slice(0, 12)
    return items
      .filter((i) => i.label.toLowerCase().includes(query))
      .slice(0, 16)
  }, [q, matters, documents, clients, projects, people])

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        setActive((a) => Math.min(a + 1, results.length - 1))
      }
      if (e.key === 'ArrowUp') {
        e.preventDefault()
        setActive((a) => Math.max(a - 1, 0))
      }
      if (e.key === 'Enter' && results[active]) {
        navigate(results[active].path)
        onClose()
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [active, results, navigate, onClose])

  useEffect(() => setActive(0), [q])

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" onClick={(e) => e.stopPropagation()}>
        <div className="modal-head">
          <input
            autoFocus
            className="form-input"
            style={{ flex: 1 }}
            placeholder="Jump to a matter, document, project, or view…"
            value={q}
            onChange={(e) => setQ(e.target.value)}
          />
          <span className="kbd">ESC</span>
        </div>
        <div className="modal-body">
          {results.map((r, i) => (
            <button
              type="button"
              key={`${r.path}-${r.label}-${i}`}
              className={`palette-item${i === active ? ' active' : ''}`}
              onClick={() => {
                navigate(r.path)
                onClose()
              }}
            >
              <span>{r.label}</span>
              <span className="mono" style={{ color: 'var(--muted-foreground)' }}>
                {r.kind}
              </span>
            </button>
          ))}
          {!results.length ? (
            <div className="empty" style={{ padding: 24 }}>
              No matches
            </div>
          ) : null}
        </div>
      </div>
    </div>
  )
}
