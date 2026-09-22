import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { apiFetch } from '../api/client'
import { useApp } from '../context/AppContext'

type Precedent = {
  id: string
  title: string
  type?: string
  rating?: number
  usage?: string
  summary?: string
  author?: string
  office?: string
}

type Clause = {
  id: string
  title: string
  category?: string
  success_rate?: string
  summary?: string
}

type KnowledgeArg = {
  argument_id?: string
  matter_id?: string
  matter_code?: string
  matter_title?: string
  issue?: string
  position?: string
  argument?: string
  outcome?: string
  practice_area?: string
}

export function KnowledgePage() {
  const { toast } = useApp()
  const [precedents, setPrecedents] = useState<Precedent[]>([])
  const [clauses, setClauses] = useState<Clause[]>([])
  const [args, setArgs] = useState<KnowledgeArg[]>([])
  const [tab, setTab] = useState<'precedents' | 'clauses' | 'arguments'>(
    'precedents',
  )
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    void (async () => {
      setLoading(true)
      try {
        const [prec, cls, argRes] = await Promise.all([
          apiFetch<{ precedents?: Precedent[] }>('/api/knowledge/precedents'),
          apiFetch<{ clauses?: Clause[] }>('/api/knowledge/clauses').catch(
            () => ({ clauses: [] }),
          ),
          apiFetch<{ items?: KnowledgeArg[] }>('/api/knowledge/arguments?limit=40').catch(
            () => ({ items: [] }),
          ),
        ])
        setPrecedents(prec.precedents || [])
        setClauses(cls.clauses || [])
        setArgs(argRes.items || [])
      } catch (err) {
        toast(err instanceof Error ? err.message : 'Failed to load knowledge')
      } finally {
        setLoading(false)
      }
    })()
  }, [toast])

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">Library</p>
          <h1>Knowledge</h1>
          <p className="lede">
            Precedents, clause banks and argument patterns across the firm.
          </p>
        </div>
      </div>

      <div className="tabs-nav">
        {(
          [
            ['precedents', `Precedents (${precedents.length})`],
            ['clauses', `Clauses (${clauses.length})`],
            ['arguments', `Arguments (${args.length})`],
          ] as const
        ).map(([id, label]) => (
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

      {loading ? <div className="empty">Loading knowledge vault…</div> : null}

      {!loading && tab === 'precedents' ? (
        <div className="stack-gap">
          {precedents.map((p) => (
            <section key={p.id} className="surface pad-card">
              <div className="chip">{p.type || 'Precedent'}</div>
              <h2 style={{ fontSize: '1.35rem', margin: '8px 0' }}>{p.title}</h2>
              <p className="lede" style={{ margin: 0 }}>
                {p.summary}
              </p>
              <div className="latency-strip">
                <span>{p.author}</span>
                <span>{p.office}</span>
                <span>{p.usage}</span>
                {p.rating != null ? <span>Rating {p.rating}</span> : null}
              </div>
            </section>
          ))}
          {!precedents.length ? <div className="empty">No precedents.</div> : null}
        </div>
      ) : null}

      {!loading && tab === 'clauses' ? (
        <div className="stack-gap">
          {clauses.map((c) => (
            <section key={c.id} className="surface pad-card">
              <div className="chip">{c.category || 'Clause'}</div>
              <h2 style={{ fontSize: '1.2rem', margin: '8px 0' }}>{c.title}</h2>
              <p className="lede" style={{ margin: 0 }}>
                {c.summary || c.success_rate || ''}
              </p>
            </section>
          ))}
          {!clauses.length ? <div className="empty">No clauses.</div> : null}
        </div>
      ) : null}

      {!loading && tab === 'arguments' ? (
        <section className="surface pad-card stack-gap-sm">
          {args.map((a, i) => (
            <div key={a.argument_id || i} className="list-row">
              <div>
                <div style={{ fontWeight: 600 }}>
                  {a.issue || a.argument_id || `Argument ${i + 1}`}
                </div>
                <div className="metadata-xs">
                  {a.matter_code || a.matter_id} · {a.practice_area || ''}
                </div>
                <p style={{ margin: '6px 0 0', fontSize: 14 }}>
                  {a.argument || a.position || ''}
                </p>
              </div>
              {a.matter_id ? (
                <Link to={`/matters/${a.matter_id}`}>Matter</Link>
              ) : null}
            </div>
          ))}
          {!args.length ? <div className="empty">No arguments indexed.</div> : null}
        </section>
      ) : null}
    </>
  )
}
