import { useEffect, useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { apiFetch } from '../api/client'
import type { AskResult } from '../api/types'
import { useApp } from '../context/AppContext'
import { SourceViewer } from '../components/SourceViewer'

const PRESETS = [
  {
    label: 'Lotus indemnity',
    query: 'What indemnity cap did we negotiate in comparable acquisitions?',
  },
  {
    label: 'MSEDCL regulatory',
    query: 'Find advice on regulatory change-of-control risk.',
  },
  {
    label: 'UNSC sanctions',
    query: 'Summarise open diligence issues across recent matters.',
  },
  {
    label: 'Chorzów principle',
    query: 'What restitution principles apply in our PCIJ corpus?',
  },
]

export function AskPage() {
  const { toast } = useApp()
  const [params] = useSearchParams()
  const [query, setQuery] = useState(params.get('q') || '')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AskResult | null>(null)
  const [debug, setDebug] = useState<Record<string, unknown> | null>(null)
  const [systemInfo, setSystemInfo] = useState<Record<string, unknown> | null>(
    null,
  )
  const [showDebug, setShowDebug] = useState(params.get('debug') === '1')
  const [viewer, setViewer] = useState<{
    documentId: string
    chunkId?: string
  } | null>(null)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)

  async function onAsk(override?: string) {
    const q = (override ?? query).trim()
    if (!q || loading) return
    setQuery(q)
    setLoading(true)
    setResult(null)
    setDebug(null)
    setElapsedMs(null)
    const t0 = performance.now()
    try {
      const [res, debugRes, info] = await Promise.all([
        apiFetch<AskResult>('/api/answers', {
          method: 'POST',
          body: JSON.stringify({ query: q, k: 10 }),
        }),
        apiFetch<Record<string, unknown>>('/api/retrieval/debug', {
          method: 'POST',
          body: JSON.stringify({ query: q, k: 10 }),
        }).catch(() => null),
        apiFetch<Record<string, unknown>>('/api/system/info').catch(() => null),
      ])
      setResult(res)
      setDebug(debugRes)
      setSystemInfo(info)
      setElapsedMs(Math.round(performance.now() - t0))
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
  const latency = result?.latency_ms || {}

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
            <div style={{ display: 'flex', gap: 8, alignItems: 'center' }}>
              <label className="metadata-xs" style={{ display: 'flex', gap: 6 }}>
                <input
                  type="checkbox"
                  checked={showDebug}
                  onChange={(e) => setShowDebug(e.target.checked)}
                />
                Debug
              </label>
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
        </div>
        {!result && !loading ? (
          <div className="suggestion-row">
            {PRESETS.map((item) => (
              <button
                key={item.label}
                type="button"
                onClick={() => void onAsk(item.query)}
              >
                {item.label}
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
        <>
          <div className="latency-strip">
            {elapsedMs != null ? <span>Wall: {elapsedMs} ms</span> : null}
            {Object.entries(latency).map(([k, v]) => (
              <span key={k}>
                {k}: {v} ms
              </span>
            ))}
            {result.provider ? <span>Provider: {result.provider}</span> : null}
          </div>

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
              <div style={{ marginTop: 24, display: 'flex', gap: 16, flexWrap: 'wrap' }}>
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
                  const chunkId = row.chunk_id
                    ? String(row.chunk_id)
                    : undefined
                  const title = String(
                    row.title || row.document_title || 'Source',
                  )
                  return (
                    <button
                      key={i}
                      type="button"
                      className="evidence-row"
                      onClick={() => {
                        if (docId) setViewer({ documentId: docId, chunkId })
                      }}
                    >
                      <span>{String(i + 1).padStart(2, '0')}</span>
                      <div>
                        <b>{title}</b>
                        <small>
                          {docId} ·{' '}
                          {String(row.matter_code || row.matter_id || '')}
                        </small>
                      </div>
                      <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                        chevron_right
                      </span>
                    </button>
                  )
                })
              ) : (
                <p className="lede">No structured citations returned.</p>
              )}
            </aside>
          </section>

          {showDebug ? (
            <details className="ask-debug" open>
              <summary style={{ cursor: 'pointer', fontWeight: 700 }}>
                Retrieval debug / provenance
              </summary>
              {systemInfo ? (
                <div className="latency-strip">
                  <span>Sprint: {String(systemInfo.sprint || '—')}</span>
                  <span>
                    Engine:{' '}
                    {String(
                      systemInfo.retrieval_engine ||
                        (systemInfo.use_engine_v2 ? 'v2' : 'legacy'),
                    )}
                  </span>
                </div>
              ) : null}
              <pre>{JSON.stringify(debug || { note: 'No debug payload' }, null, 2)}</pre>
            </details>
          ) : null}
        </>
      ) : null}

      {viewer ? (
        <SourceViewer
          documentId={viewer.documentId}
          chunkId={viewer.chunkId}
          query={query}
          onClose={() => setViewer(null)}
        />
      ) : null}
    </>
  )
}
