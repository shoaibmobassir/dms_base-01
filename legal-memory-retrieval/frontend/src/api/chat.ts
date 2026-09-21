import { apiFetch, getMemberId } from './client'
import type { ChatMessage, ChatSession } from './types'

export function listSessions() {
  return apiFetch<ChatSession[]>(
    `/api/chat/sessions?member_id=${encodeURIComponent(getMemberId())}`,
  )
}

export function createSession(title = 'New Conversation', model?: string) {
  return apiFetch<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({
      title,
      member_id: getMemberId(),
      model,
    }),
  })
}

export function getSession(sessionId: string) {
  return apiFetch<{ session: ChatSession; messages: ChatMessage[] }>(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}`,
  )
}

export function deleteSession(sessionId: string) {
  return apiFetch<void>(`/api/chat/sessions/${encodeURIComponent(sessionId)}`, {
    method: 'DELETE',
  })
}

export type StreamHandlers = {
  onDelta: (text: string) => void
  onEvent: (event: Record<string, unknown>) => void
  onCitation: (citation: Record<string, unknown>) => void
  onTitle?: (title: string) => void
  onDone?: () => void
}

export async function streamMessage(
  sessionId: string,
  content: string,
  handlers: StreamHandlers,
): Promise<void> {
  const res = await fetch(
    `/api/chat/sessions/${encodeURIComponent(sessionId)}/messages`,
    {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-Member-Id': getMemberId(),
      },
      body: JSON.stringify({ content }),
    },
  )
  if (!res.ok || !res.body) {
    throw new Error(`Chat stream failed: HTTP ${res.status}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() || ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const dataStr = line.slice(6).trim()
      if (!dataStr || dataStr === '[DONE]') {
        handlers.onDone?.()
        continue
      }
      try {
        const eventObj = JSON.parse(dataStr) as Record<string, unknown>
        const type = String(eventObj.type || '')
        if (type === 'text_delta') {
          handlers.onDelta(String(eventObj.text || ''))
        } else if (type === 'citation_data') {
          handlers.onCitation(eventObj)
        } else if (type === 'chat_title') {
          handlers.onTitle?.(String(eventObj.title || ''))
        } else if (type !== 'session_id' && type !== 'done') {
          handlers.onEvent(eventObj)
        }
      } catch {
        // ignore malformed SSE chunks
      }
    }
  }
  handlers.onDone?.()
}
