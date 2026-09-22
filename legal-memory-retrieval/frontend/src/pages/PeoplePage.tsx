import { useMemo, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function PeoplePage() {
  const { memberId } = useParams()
  const { people, matters } = useApp()
  const [q, setQ] = useState('')

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

  if (memberId) {
    const person = people.find((p) => p.member_id === memberId)
    if (!person) {
      return (
        <div>
          <div className="empty">Person not found.</div>
          <Link to="/people">← Back to people</Link>
        </div>
      )
    }
    return (
      <div>
        <div className="label-sm" style={{ marginBottom: 12, color: 'var(--muted-foreground)' }}>
          <Link to="/people" style={{ color: 'var(--muted-foreground)' }}>
            People
          </Link>
          <span style={{ margin: '0 8px' }}>/</span>
          <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
            {person.member_id}
          </span>
        </div>
        <div className="entity-header surface">
          <div>
            <p className="eyebrow">{person.role || 'Member'}</p>
            <h1 className="page-title">{person.name}</h1>
            <p className="page-sub">
              {[person.office, person.practice_area].filter(Boolean).join(' · ') ||
                'Firm member'}
            </p>
          </div>
        </div>
        <section className="surface pad-card">
          <div className="section-label">Profile</div>
          <div className="latency-strip">
            <span>ID: {person.member_id}</span>
            <span>Role: {person.role || '—'}</span>
            <span>Office: {person.office || '—'}</span>
            <span>Practice: {person.practice_area || '—'}</span>
          </div>
          <p className="lede" style={{ marginBottom: 0 }}>
            Matter staffing detail is shown on each matter&apos;s Team tab. There
            are {matters.length} matters currently loaded in workspace.
          </p>
        </section>
      </div>
    )
  }

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
              <tr key={p.member_id}>
                <td>
                  <Link
                    to={`/people/${p.member_id}`}
                    style={{
                      display: 'flex',
                      alignItems: 'center',
                      gap: 12,
                      fontWeight: 600,
                      color: 'var(--ink)',
                    }}
                  >
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
                      <div>{p.name}</div>
                      <div className="metadata-xs" style={{ marginTop: 4 }}>
                        {p.office || 'Office'}
                      </div>
                    </div>
                  </Link>
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
