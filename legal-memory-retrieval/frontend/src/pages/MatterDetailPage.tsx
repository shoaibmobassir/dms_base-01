import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { DocumentItem, Matter, ProjectItem } from '../api/types'
import { useApp } from '../context/AppContext'
import { SourceViewer } from '../components/SourceViewer'

type Tab =
  | 'overview'
  | 'team'
  | 'arguments'
  | 'timeline'
  | 'documents'
  | 'projects'
  | 'related'

type ArgItem = Record<string, unknown>
type RelatedItem = Record<string, unknown>
type TeamMember = Record<string, unknown>

export function MatterDetailPage() {
  const { matterId = '' } = useParams()
  const { toast, projects } = useApp()
  const navigate = useNavigate()
  const [matter, setMatter] = useState<(Matter & Record<string, unknown>) | null>(
    null,
  )
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [timeline, setTimeline] = useState<Array<Record<string, unknown>>>([])
  const [args, setArgs] = useState<ArgItem[]>([])
  const [related, setRelated] = useState<RelatedItem[]>([])
  const [team, setTeam] = useState<TeamMember[]>([])
  const [tab, setTab] = useState<Tab>('overview')
  const [loading, setLoading] = useState(true)
  const [viewerDoc, setViewerDoc] = useState<string | null>(null)

  const matterProjects = projects.filter((p) => p.matter_id === matterId)

  useEffect(() => {
    if (!matterId) return
    void (async () => {
      setLoading(true)
      try {
        const [detailRes, documents, tl, argumentsRes, relatedRes] =
          await Promise.all([
            apiFetch<{
              matter: Matter & Record<string, unknown>
              team?: TeamMember[]
              documents?: DocumentItem[]
            }>(`/api/matters/${encodeURIComponent(matterId)}`),
            apiFetch<{ items: DocumentItem[] }>(
              `/api/documents?matter_id=${encodeURIComponent(matterId)}&limit=50`,
            ),
            apiFetch<{ items?: Array<Record<string, unknown>> }>(
              `/api/matters/${encodeURIComponent(matterId)}/timeline`,
            ).catch(() => ({ items: [] })),
            apiFetch<{ arguments?: ArgItem[] }>(
              `/api/matters/${encodeURIComponent(matterId)}/arguments`,
            ).catch(() => ({ arguments: [] })),
            apiFetch<{ related?: RelatedItem[] }>(
              `/api/matters/${encodeURIComponent(matterId)}/related`,
            ).catch(() => ({ related: [] })),
          ])
        setMatter(detailRes.matter)
        setDocs(documents.items || detailRes.documents || [])
        setTimeline(tl.items || [])
        setArgs(argumentsRes.arguments || [])
        setRelated(relatedRes.related || [])
        setTeam(detailRes.team || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load matter')
        setMatter(null)
      } finally {
        setLoading(false)
      }
    })()
  }, [matterId, toast])

  if (loading) return <div className="empty">Loading matter…</div>
  if (!matter) {
    return (
      <div className="empty">Matter not found or not visible under ACL.</div>
    )
  }

  const tabs: Array<[Tab, string]> = [
    ['overview', 'Overview'],
    ['team', `Team (${team.length})`],
    ['arguments', `Arguments (${args.length})`],
    ['timeline', `Timeline (${timeline.length})`],
    ['documents', `Documents (${docs.length})`],
    ['projects', `Projects (${matterProjects.length})`],
    ['related', `Related (${related.length})`],
  ]

  return (
    <div>
      <div className="label-sm" style={{ marginBottom: 12, color: 'var(--muted-foreground)' }}>
        <Link to="/matters" style={{ color: 'var(--muted-foreground)' }}>
          Matters
        </Link>
        <span style={{ margin: '0 8px' }}>/</span>
        <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
          {matter.matter_code || matter.matter_id}
        </span>
      </div>

      <div className="entity-header surface">
        <div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 8 }}>
            <span className="chip">{matter.status || 'Open'}</span>
            {matter.practice_area ? (
              <span className="chip">{matter.practice_area}</span>
            ) : null}
            {matter.restricted ? (
              <span className="chip">Ethical wall</span>
            ) : null}
          </div>
          <h1 className="page-title">{matter.title}</h1>
          <p className="page-sub">
            {matter.client_name || 'Client'}
            {matter.jurisdiction ? ` · ${matter.jurisdiction}` : ''}
          </p>
        </div>
        <div className="entity-actions">
          <button
            type="button"
            className="button button-primary"
            onClick={() =>
              navigate(
                `/ask?q=${encodeURIComponent(`Summarise key issues in matter ${matter.matter_code || matter.matter_id}`)}`,
              )
            }
          >
            Ask matter
          </button>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => navigate('/projects')}
          >
            Projects
          </button>
        </div>
      </div>

      <div className="tabs-nav">
        {tabs.map(([id, label]) => (
          <button
            key={id}
            type="button"
            className={`tab-btn${tab === id ? ' is-active' : ''}`}
            onClick={() => setTab(id)}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'overview' ? (
        <section className="surface pad-card">
          <div className="section-label">Matter summary</div>
          <p style={{ margin: 0, lineHeight: 1.6 }}>
            {String(
              matter.summary ||
                matter.description ||
                `${matter.client_name || 'Client'} · ${matter.practice_area || 'Practice'} · ${matter.status || 'Open'}`,
            )}
          </p>
          <div className="latency-strip" style={{ marginTop: 16 }}>
            <span>Opened: {String(matter.opened_date || '—')}</span>
            <span>Closed: {String(matter.closed_date || '—')}</span>
            <span>Type: {String(matter.matter_type || '—')}</span>
          </div>
        </section>
      ) : null}

      {tab === 'team' ? (
        <section className="surface pad-card stack-gap-sm">
          {team.map((t, i) => (
            <div key={i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>{String(t.name || t.member_id)}</div>
                <div className="metadata-xs">
                  {String(t.role_on_matter || t.role || 'Member')}
                </div>
              </div>
            </div>
          ))}
          {!team.length ? (
            <div className="empty">No team members returned for this matter.</div>
          ) : null}
        </section>
      ) : null}

      {tab === 'arguments' ? (
        <section className="surface pad-card stack-gap-sm">
          {args.map((a, i) => (
            <div key={i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>
                  {String(a.issue || a.argument_id || `Argument ${i + 1}`)}
                </div>
                <div className="metadata-xs" style={{ marginTop: 4 }}>
                  {String(a.position || '')}
                </div>
                <p style={{ margin: '8px 0 0', fontSize: 14 }}>
                  {String(a.argument || a.summary || '')}
                </p>
              </div>
            </div>
          ))}
          {!args.length ? <div className="empty">No arguments recorded.</div> : null}
        </section>
      ) : null}

      {tab === 'timeline' ? (
        <section className="surface pad-card stack-gap-sm">
          {timeline.map((ev, i) => (
            <div key={i} className="list-row">
              <div>
                <div className="metadata-xs">
                  {String(ev.date || ev.event_date || '')}
                </div>
                <div style={{ fontWeight: 600, marginTop: 4 }}>
                  {String(ev.title || ev.description || ev.action || 'Event')}
                </div>
              </div>
            </div>
          ))}
          {!timeline.length ? <div className="empty">No timeline events.</div> : null}
        </section>
      ) : null}

      {tab === 'documents' ? (
        <section className="surface directory-surface table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Document</th>
                <th>Type</th>
                <th>Version</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {docs.map((d) => (
                <tr key={d.document_id}>
                  <td>
                    <Link to={`/documents/${d.document_id}`} style={{ fontWeight: 600 }}>
                      {d.title}
                    </Link>
                  </td>
                  <td>
                    <span className="chip">{d.document_type || 'doc'}</span>
                  </td>
                  <td className="mono">{d.version ?? '—'}</td>
                  <td>
                    <button
                      type="button"
                      className="button button-secondary"
                      onClick={() => setViewerDoc(d.document_id)}
                    >
                      Preview
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!docs.length ? <div className="empty">No documents on this matter.</div> : null}
        </section>
      ) : null}

      {tab === 'projects' ? (
        <section className="surface directory-surface table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Project</th>
                <th>Lead</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {matterProjects.map((p: ProjectItem) => (
                <tr
                  key={p.project_id}
                  onClick={() => navigate(`/projects/${p.project_id}`)}
                >
                  <td style={{ fontWeight: 600 }}>{p.title}</td>
                  <td>{p.lead_lawyer || '—'}</td>
                  <td>
                    <span className="status">{p.status || '—'}</span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!matterProjects.length ? (
            <div className="empty">No projects linked to this matter.</div>
          ) : null}
        </section>
      ) : null}

      {tab === 'related' ? (
        <section className="surface pad-card stack-gap-sm">
          {related.map((r, i) => (
            <div key={i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>
                  {String(r.title || r.matter_code || r.matter_id || `Related ${i + 1}`)}
                </div>
                <div className="metadata-xs">
                  {String(r.relation || r.relationship || r.client_name || '')}
                </div>
              </div>
              {r.matter_id ? (
                <Link to={`/matters/${String(r.matter_id)}`}>Open</Link>
              ) : null}
            </div>
          ))}
          {!related.length ? <div className="empty">No related matters.</div> : null}
        </section>
      ) : null}

      {viewerDoc ? (
        <SourceViewer documentId={viewerDoc} onClose={() => setViewerDoc(null)} />
      ) : null}
    </div>
  )
}
