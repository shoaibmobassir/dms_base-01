import { Link, useNavigate } from 'react-router-dom'
import { useApp } from '../context/AppContext'

function greeting() {
  const h = new Date().getHours()
  if (h < 12) return 'Good morning'
  if (h < 18) return 'Good afternoon'
  return 'Good evening'
}

export function HomePage() {
  const { stats, matters, documents, people, persona } = useApp()
  const navigate = useNavigate()
  const counts = stats?.counts || {}
  const member =
    people.find((p) => p.member_id === persona)?.name?.split(' ')[0] ||
    'Counsel'

  return (
    <>
      <div className="page-intro">
        <div>
          <p className="eyebrow">
            {new Date().toLocaleDateString(undefined, {
              weekday: 'long',
              day: 'numeric',
              month: 'long',
            })}
          </p>
          <h1>
            {greeting()}, {member}.
          </h1>
          <p className="lede">
            Your firm memory is current and ready for the work ahead.
          </p>
        </div>
        <button
          type="button"
          className="button button-primary"
          onClick={() => navigate('/ask')}
        >
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            auto_awesome
          </span>
          Ask FirmOS
        </button>
      </div>

      <section className="knowledge-prompt" aria-labelledby="memory-prompt-title">
        <div className="prompt-icon">
          <span className="material-symbols-outlined">auto_awesome</span>
        </div>
        <div className="prompt-copy">
          <p className="eyebrow">Firm intelligence</p>
          <h2 id="memory-prompt-title">What would you like to know?</h2>
          <p>
            Search across approved firm knowledge. Every answer stays grounded
            in source material and ACL scope.
          </p>
        </div>
        <Link className="prompt-action" to="/ask">
          Open Ask
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            north_east
          </span>
        </Link>
      </section>

      <div className="metric-grid" aria-label="Firm memory statistics">
        <article>
          <span>Active matters</span>
          <strong>{counts.matters ?? matters.length}</strong>
          <small>
            <i /> ACL-visible in this persona
          </small>
        </article>
        <article>
          <span>Indexed documents</span>
          <strong>
            {(counts.documents ?? documents.length).toLocaleString()}
          </strong>
          <small>
            <i /> Ready for retrieval
          </small>
        </article>
        <article>
          <span>People</span>
          <strong>{people.length}</strong>
          <small>
            <i /> Directory in scope
          </small>
        </article>
      </div>

      <div className="content-grid overview-grid">
        <section className="surface surface-wide">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Matter desk</p>
              <h2>Your active matters</h2>
            </div>
            <Link className="text-button" to="/matters">
              View all
              <span className="material-symbols-outlined" style={{ fontSize: 16 }}>
                chevron_right
              </span>
            </Link>
          </div>
          <div className="editorial-list">
            {matters.slice(0, 4).map((m) => (
              <button
                type="button"
                className="matter-row"
                key={m.matter_id}
                onClick={() => navigate(`/matters/${m.matter_id}`)}
              >
                <span className="matter-swatch" />
                <span className="matter-main">
                  <b>{m.title}</b>
                  <small>
                    {m.matter_code || m.matter_id} · {m.client_name || 'Client'}
                  </small>
                </span>
                <span className="matter-practice">
                  {m.practice_area || '—'}
                </span>
                <span className="material-symbols-outlined row-arrow">
                  chevron_right
                </span>
              </button>
            ))}
            {!matters.length ? (
              <div className="empty" style={{ padding: 24 }}>
                No matters in scope.
              </div>
            ) : null}
          </div>
        </section>

        <section className="surface activity-surface">
          <div className="section-heading">
            <div>
              <p className="eyebrow">Firm record</p>
              <h2>Recent documents</h2>
            </div>
            <Link className="text-button" to="/documents">
              View all
            </Link>
          </div>
          <div className="activity-list">
            {documents.slice(0, 4).map((d) => (
              <div className="activity-item" key={d.document_id}>
                <span className="avatar">
                  {(d.title || 'D')[0]?.toUpperCase()}
                </span>
                <div>
                  <b>
                    <Link to={`/documents/${d.document_id}`}>{d.title}</Link>
                  </b>
                  <small>
                    {d.matter_code || d.matter_id || 'Firm record'} ·{' '}
                    {d.doc_date || '—'}
                  </small>
                </div>
              </div>
            ))}
          </div>
        </section>
      </div>

      <section className="surface review-callout">
        <div className="callout-symbol">
          <span className="material-symbols-outlined">forum</span>
        </div>
        <div>
          <p className="eyebrow">Continue</p>
          <h3>Open multi-turn Chat when Ask needs follow-up.</h3>
          <p>
            Chat keeps tool traces and citations in one thread against the same
            retrieval stack.
          </p>
        </div>
        <button
          type="button"
          className="button button-secondary"
          onClick={() => navigate('/chat')}
        >
          Open Chat
          <span className="material-symbols-outlined" style={{ fontSize: 17 }}>
            chevron_right
          </span>
        </button>
      </section>
    </>
  )
}
