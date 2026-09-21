import { useApp } from '../context/AppContext'

function Stub({
  eyebrow,
  title,
  blurb,
}: {
  eyebrow: string
  title: string
  blurb: string
}) {
  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">{eyebrow}</p>
          <h1>{title}</h1>
          <p className="lede">{blurb}</p>
        </div>
      </div>
      <section className="surface directory-surface">
        <div className="empty" style={{ border: 'none' }}>
          This surface is ready for deeper workflows. Use Ask for citation-backed
          retrieval today.
        </div>
      </section>
    </>
  )
}

export function ProjectsPage() {
  const { projects } = useApp()
  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Workstreams</p>
          <h1>Projects</h1>
          <p className="lede">Matter-linked workstreams and staffing.</p>
        </div>
      </div>
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
            {projects.map((p) => (
              <tr key={p.project_id}>
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
        {!projects.length ? <div className="empty">No projects loaded.</div> : null}
      </section>
    </>
  )
}

export function KnowledgePage() {
  return (
    <Stub
      eyebrow="Library"
      title="Knowledge"
      blurb="Precedents and argument banks — Ask the Firm for citation-backed retrieval."
    />
  )
}

export function TeamsPage() {
  return (
    <Stub
      eyebrow="Organisation"
      title="Teams"
      blurb="Practice teams and staffing across the firm."
    />
  )
}

export function ActivityPage() {
  return (
    <Stub
      eyebrow="Audit"
      title="Activity"
      blurb="Firm activity and operational events."
    />
  )
}

export function TasksPage() {
  return (
    <Stub
      eyebrow="Operations"
      title="Tasks"
      blurb="Deadlines and operational task queues."
    />
  )
}

export function ApprovalsPage() {
  return (
    <Stub
      eyebrow="Review"
      title="Approvals"
      blurb="Items waiting on review or signature."
    />
  )
}

export function SettingsPage() {
  return (
    <Stub
      eyebrow="Admin"
      title="Settings"
      blurb="Firm administration, personas and preferences."
    />
  )
}

export function SupportPage() {
  return (
    <Stub
      eyebrow="Help"
      title="Support"
      blurb="Product support for FirmOS users."
    />
  )
}
