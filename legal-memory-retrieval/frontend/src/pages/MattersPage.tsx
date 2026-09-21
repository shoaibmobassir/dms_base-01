import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function MattersPage() {
  const { matters } = useApp()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const navigate = useNavigate()

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    return matters.filter((m) => {
      if (status !== 'all' && (m.status || '').toLowerCase() !== status) return false
      if (!query) return true
      return (
        m.title.toLowerCase().includes(query) ||
        (m.matter_code || '').toLowerCase().includes(query) ||
        (m.client_name || '').toLowerCase().includes(query) ||
        (m.practice_area || '').toLowerCase().includes(query)
      )
    })
  }, [matters, q, status])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Matter desk</p>
          <h1>Matters</h1>
          <p className="lede">
            A clear view of live work, firm context and recent activity.
          </p>
        </div>
        <button type="button" className="button button-primary">
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            add
          </span>
          New matter
        </button>
      </div>

      <section className="directory-tools">
        <div className="inline-search">
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            search
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search matters"
            aria-label="Search matters"
          />
        </div>
        <select
          className="filter-button"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="open">Open</option>
          <option value="active">Active</option>
          <option value="closed">Closed</option>
        </select>
        <div className="tool-count">{filtered.length} matters</div>
      </section>

      <section className="surface directory-surface table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Matter</th>
              <th>Practice</th>
              <th>Status</th>
              <th>Client</th>
              <th>Code</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((m) => (
              <tr
                key={m.matter_id}
                onClick={() => navigate(`/matters/${m.matter_id}`)}
              >
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <span className="matter-swatch" style={{ height: 32 }} />
                    <div>
                      <div style={{ fontWeight: 600 }}>{m.title}</div>
                      <div className="metadata-xs" style={{ marginTop: 4 }}>
                        {m.matter_code || m.matter_id}
                      </div>
                    </div>
                  </div>
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {m.practice_area || '—'}
                </td>
                <td>
                  <span className="status">{m.status || 'Open'}</span>
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {m.client_name || '—'}
                </td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {m.matter_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length ? (
          <div className="empty">No matters match.</div>
        ) : null}
      </section>
    </>
  )
}
