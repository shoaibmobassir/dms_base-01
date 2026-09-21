import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { useApp } from '../context/AppContext'

type DocDetail = {
  document_id: string
  title?: string
  document_type?: string
  matter_id?: string
  matter_code?: string
  author_name?: string
  version?: number | string
  body?: string
  text?: string
  status?: string
}

export function DocumentDetailPage() {
  const { documentId = '' } = useParams()
  const { toast } = useApp()
  const navigate = useNavigate()
  const [doc, setDoc] = useState<DocDetail | null>(null)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    if (!documentId) return
    void (async () => {
      setLoading(true)
      try {
        const detail = await apiFetch<DocDetail>(
          `/api/documents/${encodeURIComponent(documentId)}`,
        )
        setDoc(detail)
        try {
          const textRes = await apiFetch<{ text?: string; body?: string }>(
            `/api/documents/${encodeURIComponent(documentId)}/text`,
          )
          setText(textRes.text || textRes.body || detail.body || '')
        } catch {
          setText(detail.body || detail.text || '')
        }
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load document')
      } finally {
        setLoading(false)
      }
    })()
  }, [documentId, toast])

  if (loading) return <div className="empty">Loading document…</div>
  if (!doc) return <div className="empty">Document not found.</div>

  return (
    <div className="doc-workspace">
      <div className="doc-header">
        <div>
          <div
            className="label-sm"
            style={{ marginBottom: 12, color: 'var(--muted-foreground)' }}
          >
            <Link to="/documents" style={{ color: 'var(--muted-foreground)' }}>
              Documents
            </Link>
            <span style={{ margin: '0 8px' }}>/</span>
            <span style={{ color: 'var(--primary)', fontWeight: 600 }}>
              {doc.document_id}
            </span>
          </div>
          <h1 className="page-title" style={{ marginBottom: 12 }}>
            {doc.title || doc.document_id}
          </h1>
          <div
            className="metadata-xs"
            style={{
              display: 'flex',
              flexWrap: 'wrap',
              gap: 16,
              color: 'var(--muted-foreground)',
            }}
          >
            <span>
              Type:{' '}
              <span className="chip">{doc.document_type || 'Document'}</span>
            </span>
            {doc.matter_id ? (
              <span>
                Matter:{' '}
                <Link
                  to={`/matters/${doc.matter_id}`}
                  style={{
                    borderBottom: '1px dashed var(--outline)',
                    color: 'var(--charcoal)',
                  }}
                >
                  {doc.matter_code || doc.matter_id}
                </Link>
              </span>
            ) : null}
            <span className="status-dot">{doc.status || 'Final Draft'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexShrink: 0 }}>
          <button
            type="button"
            className="btn btn-ghost"
            onClick={() =>
              navigate(`/ask?q=${encodeURIComponent(`Summarise ${doc.title || doc.document_id}`)}`)
            }
          >
            <span className="material-symbols-outlined" style={{ fontSize: 18 }}>
              chat_spark
            </span>
            Ask about document
          </button>
        </div>
      </div>

      <div className="doc-split">
        <div className="doc-canvas">
          <div className="doc-page">
            <h2
              className="headline-md"
              style={{ textAlign: 'center', marginBottom: 24 }}
            >
              {doc.title || 'Document'}
            </h2>
            <p
              className="metadata-xs"
              style={{ color: 'var(--muted-foreground)', marginBottom: 20 }}
            >
              {doc.author_name || 'Author unknown'}
              {doc.version != null ? ` · v${doc.version}` : ''}
            </p>
            <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
              {text || 'No text available for this document.'}
            </div>
          </div>
        </div>

        <aside className="doc-inspector">
          <div className="inspector-head">
            <span className="material-symbols-outlined">auto_awesome</span>
            AI Insights
          </div>
          <div className="inspector-body">
            <section>
              <div className="section-label">Document summary</div>
              <p style={{ fontSize: 14, color: 'var(--on-surface)', margin: 0 }}>
                Open this document in Ask the Firm for a citation-backed summary
                grounded in retrieved passages.
              </p>
            </section>
            <section>
              <div className="section-label">Properties</div>
              <div style={{ display: 'grid', gap: 8 }}>
                <PropRow label="Author" value={doc.author_name || '—'} />
                <PropRow label="Status" value={doc.status || '—'} />
                <PropRow label="Type" value={doc.document_type || '—'} />
                <PropRow label="Version" value={String(doc.version ?? '—')} />
              </div>
            </section>
          </div>
        </aside>
      </div>
    </div>
  )
}

function PropRow({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        display: 'flex',
        justifyContent: 'space-between',
        gap: 12,
        paddingBottom: 6,
        borderBottom: '1px solid var(--surface-variant)',
      }}
    >
      <span className="metadata-xs" style={{ color: 'var(--outline)' }}>
        {label}
      </span>
      <span className="metadata-xs" style={{ color: 'var(--charcoal)' }}>
        {value}
      </span>
    </div>
  )
}
