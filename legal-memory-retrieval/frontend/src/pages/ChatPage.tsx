import { useEffect, useRef, useState } from 'react'
import {
  createSession,
  deleteSession,
  getSession,
  listSessions,
  streamMessage,
} from '../api/chat'
import type { ChatMessage, ChatSession } from '../api/types'
import { useApp } from '../context/AppContext'
import './chat.css'

function eventLabel(ev: Record<string, unknown>) {
  const type = String(ev.type || '')
  if (type === 'doc_read') return `Read: ${ev.filename || ev.document_id || ''}`
  if (type === 'doc_find') return `Search: ${ev.query || ''}`
  if (type === 'doc_created') return `Created: ${ev.filename || ''}`
  return type
}

export function ChatPage() {
  const { toast, persona } = useApp()
  const [sessions, setSessions] = useState<ChatSession[]>([])
  const [activeId, setActiveId] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [input, setInput] = useState('')
  const [streaming, setStreaming] = useState(false)
  const scrollRef = useRef<HTMLDivElement>(null)

  async function refreshSessions() {
    const list = await listSessions()
    setSessions(list)
    return list
  }

  useEffect(() => {
    void (async () => {
      try {
        const list = await refreshSessions()
        if (list[0] && !activeId) {
          setActiveId(list[0].id)
        }
      } catch {
        toast('Could not load chat sessions')
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [persona])

  useEffect(() => {
    if (!activeId) {
      setMessages([])
      return
    }
    void (async () => {
      try {
        const data = await getSession(activeId)
        setMessages(data.messages || [])
      } catch {
        setMessages([])
      }
    })()
  }, [activeId])

  useEffect(() => {
    if (scrollRef.current) {
      scrollRef.current.scrollTop = scrollRef.current.scrollHeight
    }
  }, [messages, streaming])

  async function onNew() {
    const created = await createSession()
    await refreshSessions()
    setActiveId(created.id)
    setMessages([])
  }

  async function onDelete(id: string) {
    await deleteSession(id)
    toast('Session deleted')
    const list = await refreshSessions()
    if (activeId === id) {
      setActiveId(list[0]?.id || null)
    }
  }

  async function onSend() {
    const text = input.trim()
    if (!text || streaming) return
    setInput('')

    let sessionId = activeId
    if (!sessionId) {
      const created = await createSession()
      sessionId = created.id
      setActiveId(sessionId)
      await refreshSessions()
    }

    const userMsg: ChatMessage = { role: 'user', content: text }
    const assistantMsg: ChatMessage = {
      role: 'assistant',
      content: '',
      events: [],
      citations: [],
    }
    setMessages((prev) => [...prev, userMsg, assistantMsg])
    setStreaming(true)

    let full = ''
    const events: Array<Record<string, unknown>> = []
    const citations: Array<Record<string, unknown>> = []

    try {
      await streamMessage(sessionId, text, {
        onDelta: (chunk) => {
          full += chunk
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = { ...last, content: full }
            }
            return next
          })
        },
        onEvent: (ev) => {
          events.push(ev)
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = { ...last, events: [...events] }
            }
            return next
          })
        },
        onCitation: (c) => {
          citations.push(c)
          setMessages((prev) => {
            const next = [...prev]
            const last = next[next.length - 1]
            if (last?.role === 'assistant') {
              next[next.length - 1] = { ...last, citations: [...citations] }
            }
            return next
          })
        },
        onTitle: () => {
          void refreshSessions()
        },
      })
    } catch (err) {
      toast(err instanceof Error ? err.message : 'Chat failed')
    } finally {
      setStreaming(false)
      void refreshSessions()
    }
  }

  const active = sessions.find((s) => s.id === activeId)

  return (
    <div className="chat-layout panel">
      <aside className="chat-sidebar">
        <button type="button" className="btn btn-primary" onClick={() => void onNew()}>
          New conversation
        </button>
        <div className="nav-label" style={{ color: 'var(--text-muted)' }}>
          Recent
        </div>
        <div className="chat-session-list">
          {sessions.map((s) => (
            <div
              key={s.id}
              className={`chat-session${s.id === activeId ? ' active' : ''}`}
              onClick={() => setActiveId(s.id)}
            >
              <span className="chat-session-title">
                {s.title || 'Untitled session'}
              </span>
              <button
                type="button"
                className="btn btn-ghost"
                style={{ padding: '0 4px' }}
                onClick={(e) => {
                  e.stopPropagation()
                  void onDelete(s.id)
                }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      </aside>

      <div className="chat-main">
        <div className="chat-header">
          <div>
            <h2 style={{ fontSize: 16 }}>
              {active?.title || 'New conversation'}
            </h2>
            <div className="page-sub" style={{ margin: 0 }}>
              Multi-turn assistant with citation verification
            </div>
          </div>
          {streaming ? (
            <span className="badge-live">
              <span className="pulse" /> Streaming
            </span>
          ) : null}
        </div>

        <div className="chat-messages" ref={scrollRef}>
          {!messages.length ? (
            <div className="empty">
              <div className="empty-mark">Ask</div>
              Search firm records, open documents, and get citation-backed
              answers.
            </div>
          ) : (
            messages.map((m, idx) => (
              <div
                key={idx}
                className={`chat-row ${m.role === 'user' ? 'user' : 'assistant'}`}
              >
                <div className="chat-bubble">
                  <div className="chat-role">
                    {m.role === 'user' ? 'You' : 'LEXOS Assistant'}
                  </div>
                  {(m.events || []).map((ev, i) => (
                    <div key={i} className="tool-badge">
                      {eventLabel(ev)}
                    </div>
                  ))}
                  <div className="chat-content">{m.content || (streaming && idx === messages.length - 1 ? '…' : '')}</div>
                  {(m.citations || []).length ? (
                    <div className="cite-tray">
                      {(m.citations || []).map((c, i) => (
                        <div key={i} className="cite-card">
                          <span className="chip">
                            {String(c.document_id || c.doc_id || `cite-${i + 1}`)}
                          </span>
                          <span>
                            {String(c.title || c.quote || c.filename || 'Source')}
                          </span>
                        </div>
                      ))}
                    </div>
                  ) : null}
                </div>
              </div>
            ))
          )}
        </div>

        <div className="chat-composer">
          <textarea
            className="form-textarea chat-input"
            rows={3}
            placeholder="Ask about matters, request document review, or draft a memo…"
            value={input}
            onChange={(e) => setInput(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault()
                void onSend()
              }
            }}
          />
          <button
            type="button"
            className="btn btn-primary"
            disabled={streaming || !input.trim()}
            onClick={() => void onSend()}
          >
            Send
          </button>
        </div>
      </div>
    </div>
  )
}
