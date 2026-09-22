import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { useApp } from '../context/AppContext'

type ActivityItem = {
  kind?: string
  title?: string
  subtitle?: string
  actor?: string
  date?: string | null
  matter_id?: string
  document_id?: string
}

type TaskItem = {
  id?: string
  title?: string
  due?: string
  matter_code?: string
  client_name?: string
  court?: string
  status?: string
  progress?: number
}

export function ActivityPage() {
  const { toast } = useApp()
  const [items, setItems] = useState<ActivityItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch<{ items?: ActivityItem[] }>(
          '/api/activity?limit=25',
        )
        setItems(res.items || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load activity')
      } finally {
        setLoading(false)
      }
    })()
  }, [toast])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Audit</p>
          <h1>Activity</h1>
          <p className="lede">Recent document activity visible under your ACL.</p>
        </div>
      </div>
      {loading ? <div className="empty">Loading activity…</div> : null}
      {!loading ? (
        <section className="surface pad-card stack-gap-sm">
          {items.map((item, i) => (
            <div key={i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>{item.title || 'Event'}</div>
                <div className="metadata-xs">
                  {item.subtitle || ''}
                  {item.actor ? ` · ${item.actor}` : ''}
                  {item.date ? ` · ${item.date}` : ''}
                </div>
              </div>
              {item.document_id ? (
                <Link to={`/documents/${item.document_id}`}>Open</Link>
              ) : item.matter_id ? (
                <Link to={`/matters/${item.matter_id}`}>Matter</Link>
              ) : null}
            </div>
          ))}
          {!items.length ? <div className="empty">No activity items.</div> : null}
        </section>
      ) : null}
    </>
  )
}

export function TasksPage() {
  const { toast } = useApp()
  const [items, setItems] = useState<TaskItem[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        const res = await apiFetch<{ items?: TaskItem[] }>('/api/tasks?limit=30')
        setItems(res.items || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load tasks')
      } finally {
        setLoading(false)
      }
    })()
  }, [toast])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Operations</p>
          <h1>Tasks</h1>
          <p className="lede">Project deadlines derived from open workstreams.</p>
        </div>
      </div>
      {loading ? <div className="empty">Loading tasks…</div> : null}
      {!loading ? (
        <section className="surface directory-surface table-wrap">
          <table className="table">
            <thead>
              <tr>
                <th>Task / project</th>
                <th>Matter</th>
                <th>Client</th>
                <th>Due</th>
                <th>Status</th>
              </tr>
            </thead>
            <tbody>
              {items.map((t) => (
                <tr key={t.id}>
                  <td>
                    {t.id ? (
                      <Link to={`/projects/${t.id}`} style={{ fontWeight: 600 }}>
                        {t.title}
                      </Link>
                    ) : (
                      t.title
                    )}
                  </td>
                  <td className="mono">{t.matter_code || '—'}</td>
                  <td>{t.client_name || '—'}</td>
                  <td className="mono">{t.due || '—'}</td>
                  <td>
                    <span className="status">
                      {t.status || '—'}
                      {t.progress != null ? ` · ${t.progress}%` : ''}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {!items.length ? <div className="empty">No open deadlines.</div> : null}
        </section>
      ) : null}
    </>
  )
}

export function ArchitecturePage() {
  const { toast } = useApp()
  const [info, setInfo] = useState<Record<string, unknown> | null>(null)
  const [markdown, setMarkdown] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      try {
        const [sys, md] = await Promise.all([
          apiFetch<Record<string, unknown>>('/api/system/info'),
          fetch('/api/system/architecture').then(async (r) =>
            r.ok ? r.text() : 'Architecture documentation not available.',
          ),
        ])
        setInfo(sys)
        setMarkdown(md)
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load architecture')
      } finally {
        setLoading(false)
      }
    })()
  }, [toast])

  const features = (info?.features || {}) as Record<string, unknown>

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Platform</p>
          <h1>Architecture</h1>
          <p className="lede">
            Retrieval fabric status and system documentation for operators.
          </p>
        </div>
        <a
          className="button button-secondary"
          href="/api/system/architecture"
          target="_blank"
          rel="noreferrer"
        >
          Raw markdown
        </a>
      </div>

      {loading ? <div className="empty">Loading system info…</div> : null}

      {!loading && info ? (
        <section className="surface pad-card" style={{ marginBottom: 16 }}>
          <div className="latency-strip">
            <span>Sprint: {String(info.sprint || '—')}</span>
            <span>Engine: {String(info.retrieval_engine || '—')}</span>
            <span>Index: {String(info.index_version || '—')}</span>
          </div>
          <div className="feature-chip-row">
            {Object.entries(features).map(([key, val]) => (
              <span key={key} className="chip">
                {key}: {String(val)}
              </span>
            ))}
          </div>
          <a href="/docs" target="_blank" rel="noreferrer" className="text-button">
            OpenAPI docs
          </a>
        </section>
      ) : null}

      {!loading ? (
        <section className="surface pad-card">
          <pre className="arch-markdown">{markdown}</pre>
        </section>
      ) : null}
    </>
  )
}

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
          This surface is not wired yet. Use Ask, Chat, Matters and Projects for
          live workflows.
        </div>
      </section>
    </>
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
