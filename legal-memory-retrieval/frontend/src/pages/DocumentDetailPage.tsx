import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  compareVersions,
  createDevelopingVersion,
  getDocumentDetail,
  getDocumentText,
  getVersion,
  listVersions,
  type DocVersion,
} from '../api/documents'
import { useApp } from '../context/AppContext'
import { SourceViewer } from '../components/SourceViewer'

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
  const { toast, people } = useApp()
  const navigate = useNavigate()
  const [doc, setDoc] = useState<DocDetail | null>(null)
  const [text, setText] = useState('')
  const [loading, setLoading] = useState(true)
  const [versions, setVersions] = useState<DocVersion[]>([])
  const [diffText, setDiffText] = useState<string | null>(null)
  const [viewerOpen, setViewerOpen] = useState(false)

  useEffect(() => {
    if (!documentId) return
    void (async () => {
      setLoading(true)
      try {
        const detail = (await getDocumentDetail(documentId)) as DocDetail
        setDoc(detail)
        try {
          const textRes = await getDocumentText(documentId)
          setText(textRes.text || textRes.body || detail.body || '')
        } catch {
          setText(detail.body || detail.text || '')
        }
        const v = await listVersions(documentId).catch(() => ({ versions: [] }))
        setVersions(v.versions || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load document')
      } finally {
        setLoading(false)
      }
    })()
  }, [documentId, toast])

  async function onDevelop() {
    try {
      const res = await createDevelopingVersion(
        documentId,
        people[0]?.name || 'Counsel',
      )
      toast(`Created ${res.version?.version_label || 'developing version'}`)
      const v = await listVersions(documentId)
      setVersions(v.versions || [])
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not create version')
    }
  }

  async function onCompareLatest() {
    if (versions.length < 2) {
      toast('Need at least two versions to compare')
      return
    }
    try {
      const diff = await compareVersions(
        documentId,
        versions[0].version_id,
        versions[1].version_id,
      )
      setDiffText(diff.diff || 'No diff returned')
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Diff failed')
    }
  }

  async function onOpenVersion(versionId: string) {
    try {
      const data = await getVersion(documentId, versionId)
      setText(data.version?.body || '')
      setDiffText(null)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Could not load version')
    }
  }

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
                <Link to={`/matters/${doc.matter_id}`}>
                  {doc.matter_code || doc.matter_id}
                </Link>
              </span>
            ) : null}
            <span className="status-dot">{doc.status || 'Final Draft'}</span>
          </div>
        </div>
        <div style={{ display: 'flex', gap: 10, flexShrink: 0, flexWrap: 'wrap' }}>
          <button
            type="button"
            className="button button-secondary"
            onClick={() => setViewerOpen(true)}
          >
            Source viewer
          </button>
          <button
            type="button"
            className="button button-primary"
            onClick={() =>
              navigate(
                `/ask?q=${encodeURIComponent(`Summarise ${doc.title || doc.document_id}`)}`,
              )
            }
          >
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
            {diffText != null ? (
              <pre className="diff-pane">{diffText}</pre>
            ) : (
              <div style={{ whiteSpace: 'pre-wrap', lineHeight: 1.7 }}>
                {text || 'No text available for this document.'}
              </div>
            )}
          </div>
        </div>

        <aside className="doc-inspector">
          <div className="inspector-head">
            <span className="material-symbols-outlined">info</span>
            Properties
          </div>
          <div className="inspector-body">
            <section>
              <div className="section-label">Ask for analysis</div>
              <p style={{ fontSize: 14, margin: 0 }}>
                Use Ask FirmOS for citation-backed summaries. This panel does not
                generate AI copy locally.
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
            <section>
              <div className="section-label">
                Versions ({versions.length})
              </div>
              <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 8 }}>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void onDevelop()}
                >
                  Develop
                </button>
                <button
                  type="button"
                  className="button button-secondary"
                  onClick={() => void onCompareLatest()}
                >
                  Compare latest
                </button>
                {diffText != null ? (
                  <button
                    type="button"
                    className="button button-secondary"
                    onClick={() => setDiffText(null)}
                  >
                    Clear diff
                  </button>
                ) : null}
              </div>
              <div className="stack-gap-sm">
                {versions.map((v) => (
                  <button
                    key={v.version_id}
                    type="button"
                    className="list-row"
                    style={{ width: '100%', textAlign: 'left' }}
                    onClick={() => void onOpenVersion(v.version_id)}
                  >
                    <div>
                      <div style={{ fontWeight: 600 }}>
                        v{v.version_number} · {v.version_label || v.title || 'Version'}
                      </div>
                      <div className="metadata-xs">
                        {v.author_name || 'Unknown'} · {v.version_status || ''}
                      </div>
                    </div>
                  </button>
                ))}
                {!versions.length ? (
                  <div className="metadata-xs">No version history yet.</div>
                ) : null}
              </div>
            </section>
          </div>
        </aside>
      </div>

      {viewerOpen ? (
        <SourceViewer
          documentId={documentId}
          onClose={() => setViewerOpen(false)}
        />
      ) : null}
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
        borderBottom: '1px solid var(--border)',
      }}
    >
      <span className="metadata-xs" style={{ color: 'var(--muted-foreground)' }}>
        {label}
      </span>
      <span className="metadata-xs">{value}</span>
    </div>
  )
}
