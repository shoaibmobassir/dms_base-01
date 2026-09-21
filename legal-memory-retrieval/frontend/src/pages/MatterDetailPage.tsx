import { useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { DocumentItem, Matter } from '../api/types'
import { useApp } from '../context/AppContext'

export function MatterDetailPage() {
  const { matterId = '' } = useParams()
  const { toast } = useApp()
  const [matter, setMatter] = useState<Matter | null>(null)
  const [docs, setDocs] = useState<DocumentItem[]>([])
  const [timeline, setTimeline] = useState<Array<Record<string, unknown>>>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!matterId) return
    void (async () => {
      setLoading(true)
      try {
        const [detail, documents, tl] = await Promise.all([
          apiFetch<Matter & Record<string, unknown>>(
            `/api/matters/${encodeURIComponent(matterId)}`,
          ),
          apiFetch<{ items: DocumentItem[] }>(
            `/api/documents?matter_id=${encodeURIComponent(matterId)}&limit=50`,
          ),
          apiFetch<{ items?: Array<Record<string, unknown>> }>(
            `/api/matters/${encodeURIComponent(matterId)}/timeline`,
          ).catch(() => ({ items: [] })),
        ])
        setMatter(detail)
        setDocs(documents.items || [])
        setTimeline(tl.items || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load matter')
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

      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12, marginBottom: 8 }}>
        <span className="chip">{matter.status || 'Open'}</span>
        {matter.practice_area ? (
          <span className="chip">{matter.practice_area}</span>
        ) : null}
      </div>

      <h1 className="page-title">{matter.title}</h1>
      <p className="page-sub">
        {matter.client_name || 'Client'}
        {matter.jurisdiction ? ` · ${matter.jurisdiction}` : ''}
      </p>

      <div className="section-label" style={{ marginTop: 32 }}>
        Documents
      </div>
      <div className="table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Type</th>
              <th>Version</th>
              <th>ID</th>
            </tr>
          </thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.document_id}>
                <td>
                  <Link
                    to={`/documents/${d.document_id}`}
                    style={{ fontWeight: 600, color: 'var(--ink)' }}
                  >
                    {d.title}
                  </Link>
                </td>
                <td>
                  <span className="chip">{d.document_type || 'doc'}</span>
                </td>
                <td className="mono">{d.version ?? '—'}</td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {d.document_id}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {!docs.length ? <div className="empty">No documents on this matter.</div> : null}

      {timeline.length ? (
        <>
          <div className="section-label" style={{ marginTop: 32 }}>
            Timeline
          </div>
          <div style={{ display: 'grid', gap: 8 }}>
            {timeline.slice(0, 12).map((ev, i) => (
              <div
                key={i}
                style={{
                  border: '1px solid var(--outline-variant)',
                  borderRadius: 8,
                  padding: 14,
                  background: 'var(--surface-container-lowest)',
                }}
              >
                <div className="metadata-xs" style={{ color: 'var(--muted-foreground)' }}>
                  {String(ev.date || ev.event_date || '')}
                </div>
                <div style={{ marginTop: 4 }}>
                  {String(ev.title || ev.description || ev.action || 'Event')}
                </div>
              </div>
            ))}
          </div>
        </>
      ) : null}
    </div>
  )
}
