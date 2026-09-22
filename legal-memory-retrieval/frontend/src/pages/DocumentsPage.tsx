import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ingestDocument } from '../api/documents'
import { useApp } from '../context/AppContext'

export function DocumentsPage() {
  const { documents, matters, people, refresh, toast } = useApp()
  const [q, setQ] = useState('')
  const [showIngest, setShowIngest] = useState(false)
  const [title, setTitle] = useState('')
  const [matterId, setMatterId] = useState(matters[0]?.matter_id || '')
  const [body, setBody] = useState('')
  const [docType, setDocType] = useState('Contract Draft')
  const [saving, setSaving] = useState(false)
  const navigate = useNavigate()

  const filtered = useMemo(() => {
    const query = q.trim().toLowerCase()
    if (!query) return documents
    return documents.filter(
      (d) =>
        d.title.toLowerCase().includes(query) ||
        d.document_id.toLowerCase().includes(query) ||
        (d.matter_code || '').toLowerCase().includes(query) ||
        (d.author_name || '').toLowerCase().includes(query) ||
        (d.document_type || '').toLowerCase().includes(query),
    )
  }, [documents, q])

  async function onIngest(e: FormEvent) {
    e.preventDefault()
    if (!title.trim() || !matterId || !body.trim()) {
      toast('Title, matter and body are required')
      return
    }
    setSaving(true)
    try {
      const res = await ingestDocument({
        title: title.trim(),
        matter_id: matterId,
        body: body.trim(),
        document_type: docType,
        author_name: people[0]?.name,
        status: 'Draft',
      })
      await refresh()
      toast(
        `Ingested ${res.document_id || 'document'} (${res.chunks_indexed ?? 0} chunks)`,
      )
      setShowIngest(false)
      setTitle('')
      setBody('')
      if (res.document_id) navigate(`/documents/${res.document_id}`)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Ingest failed')
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Repository</p>
          <h1>Documents</h1>
          <p className="lede">
            Indexed filings and firm work product, searchable across matters.
          </p>
        </div>
        <button
          type="button"
          className="button button-primary"
          onClick={() => setShowIngest((v) => !v)}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            upload
          </span>
          {showIngest ? 'Hide ingest' : 'Metadata ingest'}
        </button>
      </div>

      {showIngest ? (
        <section className="ingest-panel">
          <p className="eyebrow">Dev ingest</p>
          <h2 style={{ fontSize: '1.2rem', margin: '4px 0 8px' }}>
            Register document text (not binary upload)
          </h2>
          <p className="lede" style={{ marginTop: 0 }}>
            Posts JSON metadata + body to <span className="mono">POST /api/documents/ingest</span>.
            Does not upload files from disk.
          </p>
          <form onSubmit={(e) => void onIngest(e)}>
            <label>
              Title
              <input
                className="form-input"
                value={title}
                onChange={(e) => setTitle(e.target.value)}
                required
              />
            </label>
            <label>
              Matter
              <select
                className="form-input"
                value={matterId}
                onChange={(e) => setMatterId(e.target.value)}
                required
              >
                {matters.map((m) => (
                  <option key={m.matter_id} value={m.matter_id}>
                    {m.matter_code || m.matter_id} — {m.title}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Type
              <input
                className="form-input"
                value={docType}
                onChange={(e) => setDocType(e.target.value)}
              />
            </label>
            <label>
              Body text
              <textarea
                className="form-textarea"
                rows={6}
                value={body}
                onChange={(e) => setBody(e.target.value)}
                required
                placeholder="Paste document text to index…"
              />
            </label>
            <div className="form-actions">
              <button
                type="button"
                className="button button-secondary"
                onClick={() => setShowIngest(false)}
              >
                Cancel
              </button>
              <button
                type="submit"
                className="button button-primary"
                disabled={saving}
              >
                {saving ? 'Ingesting…' : 'Ingest'}
              </button>
            </div>
          </form>
        </section>
      ) : null}

      <section className="directory-tools">
        <div className="inline-search">
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            search
          </span>
          <input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="Search documents"
            aria-label="Search documents"
          />
        </div>
        <div className="tool-count">{filtered.length} documents</div>
      </section>

      <section className="surface directory-surface table-wrap">
        <table className="table">
          <thead>
            <tr>
              <th>Document</th>
              <th>Matter</th>
              <th>Type</th>
              <th>Owner</th>
              <th>Status</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((d) => (
              <tr
                key={d.document_id}
                onClick={() => navigate(`/documents/${d.document_id}`)}
              >
                <td>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                    <span
                      className="material-symbols-outlined"
                      style={{ color: 'var(--primary)', fontSize: 20 }}
                    >
                      description
                    </span>
                    <div>
                      <div style={{ fontWeight: 600 }}>{d.title}</div>
                      <div className="metadata-xs" style={{ marginTop: 4 }}>
                        {d.document_id}
                      </div>
                    </div>
                  </div>
                </td>
                <td>
                  {d.matter_id ? (
                    <Link
                      to={`/matters/${d.matter_id}`}
                      onClick={(e) => e.stopPropagation()}
                    >
                      {d.matter_code || d.matter_id}
                    </Link>
                  ) : (
                    '—'
                  )}
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {d.document_type || 'Document'}
                </td>
                <td style={{ color: 'var(--muted-foreground)' }}>
                  {d.author_name || '—'}
                </td>
                <td>
                  <span className="status">{d.status || 'Indexed'}</span>
                </td>
                <td className="mono" style={{ color: 'var(--muted-foreground)' }}>
                  {d.doc_date || '—'}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        {!filtered.length ? (
          <div className="empty">No documents match.</div>
        ) : null}
      </section>
    </>
  )
}
