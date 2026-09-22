import { useMemo, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function ClientsPage() {
  const { clientId } = useParams()
  const { clients, matters } = useApp()
  const [q, setQ] = useState('')
  const navigate = useNavigate()

  const rows = useMemo(() => {
    const query = q.trim().toLowerCase()
    return clients
      .filter(
        (c) =>
          !query ||
          c.name.toLowerCase().includes(query) ||
          (c.industry || '').toLowerCase().includes(query) ||
          c.client_id.toLowerCase().includes(query),
      )
      .map((c) => {
        const related = matters.filter((m) => m.client_id === c.client_id)
        return {
          ...c,
          activeMatters: related.filter((m) =>
            ['open', 'active'].includes((m.status || '').toLowerCase()),
          ).length,
          totalMatters: related.length,
        }
      })
  }, [clients, matters, q])

  if (clientId) {
    const client = clients.find((c) => c.client_id === clientId)
    const related = matters.filter((m) => m.client_id === clientId)
    if (!client) {
      return (
        <div>
          <div className="empty">Client not found.</div>
          <Link to="/clients">← Back to clients</Link>
        </div>
      )
    }
    return (
      <div>
        <div className="label-sm" style={{ marginBottom: 12, color: 'var(--muted-foreground)' }}>
          <Link to="/clients" style={{ color: 'var(--muted-foreground)' }}>
            Clients
          </Link>
          <span style={{ margin: '0 8px' }}>/</span>
          <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
            {client.client_id}
          </span>
        </div>
        <div className="entity-header surface">
          <div>
            <p className="eyebrow">Client</p>
            <h1 className="page-title">{client.name}</h1>
            <p className="page-sub">
              {client.industry || 'Industry n/a'} · {client.status || 'Client'}
            </p>
          </div>
        </div>
        <div className="section-label">Matters ({related.length})</div>
        <section className="surface directory-surface table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Matter</th>
                <th>Practice</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {related.map((m) => (
                <tr
                  key={m.matter_id}
                  onClick={() => navigate(`/matters/${m.matter_id}`)}
                >
                  <td style={{ fontWeight: 600 }}>{m.title}</td>
                  <td>{m.practice_area || '—'}</td>
                  <td>
                    <span className="status">{m.status || 'Open'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!related.length ? (
            <div className="empty">No matters for this client under ACL.</div>
          ) : null}
        </section>
      </div>
    )
  }

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Relationships</p>
          <h1>Clients</h1>
          <p className="lede">
            Institutional relationships and active matter coverage.
          </p>
        </div>
      </div>

      <section className="directory-tools">
        <div className="inline-search">
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            search
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search clients"
            aria-label="Search clients"
          />
        </div>
        <div className="tool-count">{rows.length} clients</div>
      </section>

      <section className="surface directory-surface table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Client</th>
              <th>Industry</th>
              <th>Active</th>
              <th>Total</th>
              <th>ID</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((c) => (
              <tr
                key={c.client_id}
                onClick={() => navigate(`/clients/${c.client_id}`)}
              >
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div
                      style={{
                        width: 32,
                        height: 32,
                        borderRadius: 4,
                        background: 'var(--wine-soft)',
                        color: 'var(--wine)',
                        display: 'grid',
                        placeItems: 'center',
                        fontFamily: 'var(--font-sans)',
                        fontWeight: 700,
                        fontSize: 13,
                      }}
                    >
                      {(c.name || '?').charAt(0).toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{c.name}</div>
                      <div className="metadata-xs" style={{ marginTop: 4 }}>
                        {c.status || 'Client'}
                      </div>
                    </div>
                  </div>
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {c.industry || '—'}
                </td>
                <td>
                  <span className="status">{c.activeMatters}</span>
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {c.totalMatters}
                </td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {c.client_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!rows.length ? <div className="empty">No clients loaded.</div> : null}
      </section>
    </>
  )
}
