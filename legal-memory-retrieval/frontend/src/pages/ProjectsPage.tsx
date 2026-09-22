import { useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'
import { CreateProjectModal } from '../components/CreateProjectModal'

export function ProjectsPage() {
  const { projects } = useApp()
  const [q, setQ] = useState('')
  const [status, setStatus] = useState('all')
  const [createOpen, setCreateOpen] = useState(false)
  const navigate = useNavigate()

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    return projects.filter((p) => {
      if (status !== 'all' && (p.status || '').toLowerCase() !== status.toLowerCase()) {
        return false
      }
      if (!query) return true
      return (
        p.title.toLowerCase().includes(query) ||
        (p.matter_id || '').toLowerCase().includes(query) ||
        (p.team || '').toLowerCase().includes(query) ||
        (p.lead_lawyer || '').toLowerCase().includes(query) ||
        p.project_id.toLowerCase().includes(query)
      )
    })
  }, [projects, q, status])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Workstreams</p>
          <h1>Projects</h1>
          <p className="lede">Matter-linked workstreams, staffing and milestones.</p>
        </div>
        <button
          type="button"
          className="button button-primary"
          onClick={() => setCreateOpen(true)}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            add
          </span>
          New project
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
            placeholder="Search projects"
            aria-label="Search projects"
          />
        </div>
        <select
          className="filter-button"
          value={status}
          onChange={(e) => setStatus(e.target.value)}
        >
          <option value="all">All statuses</option>
          <option value="In Progress">In Progress</option>
          <option value="Completed">Completed</option>
          <option value="On Hold">On Hold</option>
        </select>
        <div className="tool-count">{filtered.length} projects</div>
      </section>

      <section className="surface directory-surface table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Title</th>
              <th>Matter</th>
              <th>Team</th>
              <th>Lead</th>
              <th>Status</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((p) => (
              <tr
                key={p.project_id}
                onClick={() => navigate(`/projects/${p.project_id}`)}
              >
                <td style={{ fontWeight: 600 }}>{p.title}</td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {p.matter_id || '—'}
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {p.team || '—'}
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {p.lead_lawyer || '—'}
                </td>
                <td>
                  <span className="status">{p.status || '—'}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length ? <div className="empty">No projects match.</div> : null}
      </section>

      {createOpen ? (
        <CreateProjectModal onClose={() => setCreateOpen(false)} />
      ) : null}
    </>
  )
}
