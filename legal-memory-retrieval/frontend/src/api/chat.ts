import { ApiError, apiFetch, authHeaders } from './client'
import type { ChatEvent, ChatMessage, ChatModel, ChatSession, Citation } from './types'

const enc = encodeURIComponent

export function listSessions() {
  return apiFetch<ChatSession[]>('/api/chat/sessions')
}

/** No title: the server titles the conversation from its first question. */
export function createSession(model?: string) {
  return apiFetch<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ model }),
  })
}

export function getSession(sessionId: string) {
  return apiFetch<{ session: ChatSession; messages: ChatMessage[] }>(`/api/chat/sessions/${enc(sessionId)}`)
}

export function renameSession(sessionId: string, title: string) {
  return apiFetch<ChatSession>(`/api/chat/sessions/${enc(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify({ title }),
  })
}

export function deleteSession(sessionId: string) {
  return apiFetch<void>(`/api/chat/sessions/${enc(sessionId)}`, { method: 'DELETE' })
}

export function listModels() {
  return apiFetch<{ models: ChatModel[]; configured: boolean }>('/api/chat/models')
}

export function listSuggestions() {
  return apiFetch<{ suggestions: string[] }>('/api/chat/suggestions').then((r) => r.suggestions)
}

export type StreamHandlers = {
  onDelta: (text: string) => void
  onEvent: (event: ChatEvent) => void
  onCitation: (citation: Citation) => void
  onTitle: (title: string) => void
  onError: (message: string) => void
}

/**
 * POST a message and consume the SSE response. Aborting `signal` (Stop) closes the
 * connection; the server keeps whatever was generated so far.
 */
export type WorkMode = 'reason' | 'research' | 'review' | 'cite'

export async function streamMessage(
  sessionId: string,
  content: string,
  handlers: StreamHandlers,
  signal: AbortSignal,
  options?: { mode?: WorkMode },
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${enc(sessionId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content, mode: options?.mode }),
    signal,
  })
  if (!res.ok || !res.body) {
    throw new ApiError(res.status, await res.text())
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6).trim()
      if (!data || data === '[DONE]') continue
      let event: ChatEvent
      try {
        event = JSON.parse(data) as ChatEvent
      } catch {
        continue // partial or malformed chunk
      }
      switch (event.type) {
        case 'text_delta':
          handlers.onDelta(String(event.text ?? ''))
          break
        case 'citation_data':
          handlers.onCitation(event as Citation)
          break
        case 'chat_title':
          handlers.onTitle(String(event.title ?? ''))
          break
        case 'error':
          handlers.onError(String(event.message ?? 'The assistant failed to answer.'))
          break
        case 'session_id':
        case 'done':
          break
        default:
          handlers.onEvent(event)
      }
    }
  }
}
