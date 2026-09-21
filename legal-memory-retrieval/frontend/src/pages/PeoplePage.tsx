import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function PeoplePage() {
  const { people } = useApp()
  const [q, setQ] = useState('')
  const navigate = useNavigate()

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    if (!query) return people
    return people.filter(
      (p) =>
        p.name.toLowerCase().includes(query) ||
        (p.role || '').toLowerCase().includes(query) ||
        (p.office || '').toLowerCase().includes(query) ||
        (p.practice_area || '').toLowerCase().includes(query) ||
        p.member_id.toLowerCase().includes(query),
    )
  }, [people, q])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Firm network</p>
          <h1>People</h1>
          <p className="lede">
            Colleagues, roles and practice coverage across the chambers.
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
            placeholder="Search people"
            aria-label="Search people"
          />
        </div>
        <div className="tool-count">{filtered.length} people</div>
      </section>

      <section className="surface directory-surface table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Professional</th>
              <th>Role</th>
              <th>Office</th>
              <th>Practice</th>
              <th>ID</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr
                key={p.member_id}
                onClick={() => navigate(`/people/${p.member_id}`)}
              >
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
                    <div
                      style={{
                        width: 36,
                        height: 36,
                        borderRadius: 999,
                        background: 'var(--wine-soft)',
                        color: 'var(--wine)',
                        display: 'grid',
                        placeItems: 'center',
                        fontFamily: 'var(--font-sans)',
                        fontSize: 11,
                        fontWeight: 700,
                        letterSpacing: '0.04em',
                      }}
                    >
                      {p.name
                        .split(' ')
                        .map((w) => w[0])
                        .slice(0, 2)
                        .join('')
                        .toUpperCase()}
                    </div>
                    <div>
                      <div style={{ fontWeight: 600 }}>{p.name}</div>
                      <div className="metadata-xs" style={{ marginTop: 4 }}>
                        {p.office || 'Office'}
                      </div>
                    </div>
                  </div>
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {p.role || '—'}
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {p.office || '—'}
                </td>
                <td>
                  {p.practice_area ? (
                    <span className="status">{p.practice_area}</span>
                  ) : (
                    '—'
                  )}
                </td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {p.member_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length ? <div className="empty">No people match.</div> : null}
      </section>
    </>
  )
}
