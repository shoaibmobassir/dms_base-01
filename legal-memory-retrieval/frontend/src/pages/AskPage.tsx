import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { AskResult } from '../api/types'
import { useApp } from '../context/AppContext'

const SUGGESTIONS = [
  'What indemnity cap did we negotiate in comparable acquisitions?',
  'Find advice on regulatory change-of-control risk.',
  'Summarise open diligence issues across recent matters.',
]

export function AskPage() {
  const { toast } = useApp()
  const [params] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') || '')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AskResult | null>(null)

  async function onAsk(override?: string) {
    const q = (override ?? query).trim()
    if (!q || loading) return
    setQuery(q)
    setLoading(true)
    setResult(null)
    try {
      const res = await apiFetch<AskResult>('/api/answers', {
        method: 'POST',
        body: JSON.stringify({ query: q, k: 10 }),
      })
      setResult(res)
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Ask failed')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    const q = params.get('q')
    if (q) void onAsk(q)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const citations = result?.structured_citations || result?.sources || []

  return (
    <>
      <div className="page-intro narrow-intro">
        <p className="eyebrow">Institutional intelligence</p>
        <h1>Ask FirmOS</h1>
        <p className="lede">
          Explore the firm&apos;s collective work. Every answer is linked to the
          records it relies on.
        </p>
      </div>

      <section className="ask-surface">
        <label htmlFor="firm-question">
          Ask a question about your firm&apos;s work
        </label>
        <div className="ask-composer">
          <textarea
            id="firm-question"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="For example, what indemnity positions have we taken in comparable acquisitions?"
            rows={4}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
                e.preventDefault()
                void onAsk()
              }
            }}
          />
          <div>
            <span>Sources and ethical walls are applied automatically.</span>
            <button
              type="button"
              className="button button-primary"
              disabled={loading || !query.trim()}
              onClick={() => void onAsk()}
            >
              <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
                auto_awesome
              </span>
              {loading ? 'Asking…' : 'Ask'}
            </button>
          </div>
        </div>
        {!result && !loading ? (
          <div className="suggestion-row">
            {SUGGESTIONS.map((item) => (
              <button key={item} type="button" onClick={() => void onAsk(item)}>
                {item}
                <span className="material-symbols-outlined" style={{ fontSize: 14 }}>
                  north_east
                </span>
              </button>
            ))}
          </div>
        ) : null}
      </section>

      {loading ? (
        <div className="empty">Synthesizing grounded answer…</div>
      ) : null}

      {result ? (
        <section className="answer-layout">
          <article className="surface answer-card">
            <div className="answer-top">
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                auto_awesome
              </span>
              <span>Grounded answer</span>
            </div>
            {result.key_finding ? (
              <h2>{result.key_finding}</h2>
            ) : (
              <h2>
                {result.abstained
                  ? 'Insufficient evidence to answer'
                  : 'Answer from firm memory'}
              </h2>
            )}
            <p>
              {result.abstained
                ? result.reason || 'The model abstained.'
                : result.answer || 'No answer returned.'}
            </p>
            <div style={{ marginTop: 24 }}>
              <Link className="text-button" to="/chat">
                Continue in Chat
                <span className="material-symbols-outlined" style={{ fontSize: 15 }}>
                  north_east
                </span>
              </Link>
            </div>
          </article>

          <aside className="evidence-panel">
            <p className="eyebrow">Evidence · {citations.length} sources</p>
            <h3>Source record</h3>
            {citations.length ? (
              citations.map((c, i) => {
                const row = c as Record<string, unknown>
                const docId = String(
                  row.document_id || row.doc_id || row.id || '',
                )
                const title = String(
                  row.title || row.document_title || 'Source',
                )
                return (
                  <Link
                    key={i}
                    className="evidence-row"
                    to={docId ? `/documents/${docId}` : '/documents'}
                  >
                    <span>{String(i + 1).padStart(2, '0')}</span>
                    <div>
                      <b>{title}</b>
                      <small>
                        {docId} · {String(row.matter_code || row.matter_id || '')}
                      </small>
                    </div>
                    <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                      chevron_right
                    </span>
                  </Link>
                )
              })
            ) : (
              <p className="lede">No structured citations returned.</p>
            )}
          </aside>
        </section>
      ) : null}
    </>
  )
}
