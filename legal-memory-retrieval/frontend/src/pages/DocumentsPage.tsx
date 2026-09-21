import { useMemo, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

export function DocumentsPage() {
  const { documents } = useApp()
  const [q, setQ] = useState('')
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
        <button type="button" className="button button-primary">
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            upload
          </span>
          Upload
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
