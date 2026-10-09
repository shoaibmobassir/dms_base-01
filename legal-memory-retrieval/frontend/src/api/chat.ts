import { ApiError, apiFetch, authHeaders } from './client'
import type { Attachment, ChatEvent, ChatMessage, ChatModel, ChatSession, Citation, EditProposal } from './types'

const enc = encodeURIComponent

export function listSessions() {
  return apiFetch<ChatSession[]>('/api/chat/sessions')
}

/** No title: the server titles the conversation from its first question. */
export function createSession(model?: string, matterId?: string, workspace?: { kind: 'matter' | 'project' | 'library'; id: string }) {
  return apiFetch<ChatSession>('/api/chat/sessions', {
    method: 'POST',
    body: JSON.stringify({ model, matter_id: matterId || undefined, workspace_kind: workspace?.kind, workspace_id: workspace?.id }),
  })
}

/** The caller's conversations in one workspace (the workbench's Assistant), newest first. */
export function listWorkspaceSessions(kind: 'matter' | 'project' | 'library', id: string) {
  return apiFetch<ChatSession[]>(`/api/chat/sessions?workspace_kind=${kind}&workspace_id=${enc(id)}&limit=20`)
}

/** Pin or unpin a conversation, or limit it to a matter ("" clears the matter). */
export function updateSession(sessionId: string, patch: { pinned?: boolean; matter_id?: string }) {
  return apiFetch<ChatSession>(`/api/chat/sessions/${enc(sessionId)}`, {
    method: 'PATCH',
    body: JSON.stringify(patch),
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

/** Record accept / reject on one suggested edit. */
export function decideEdit(sessionId: string, messageId: string, editId: string, status: EditProposal['status']) {
  return apiFetch<EditProposal>(
    `/api/chat/sessions/${enc(sessionId)}/messages/${enc(messageId)}/edits/${enc(editId)}`,
    { method: 'PATCH', body: JSON.stringify({ status }) },
  )
}

/** Accept, reject or reset every edit to one document in a message. */
export function decideAllEdits(sessionId: string, messageId: string, documentId: string, status: EditProposal['status']) {
  return apiFetch<{
    updated: number
    status: string
    /** Edits that could not be placed in the document, by id, with the reason. */
    failed: Record<string, string>
    edits: EditProposal[]
    version_number: number | null
  }>(
    `/api/chat/sessions/${enc(sessionId)}/messages/${enc(messageId)}/edits`,
    { method: 'PATCH', body: JSON.stringify({ status, document_id: documentId }) },
  )
}

/** Build a tracked-changes Word file from the accepted edits to one document. */
export function exportEdits(sessionId: string, messageId: string, documentId: string) {
  return apiFetch<{
    filename: string
    download_url: string
    document_id: string
    applied: number
    /** Paragraph edits: written into the original Word file, and saved as a new version. */
    tracked_in_original?: boolean
    /** Edits already in the document: a Word redline of what they changed. */
    redline?: boolean
    version_label?: string | null
  }>(
    `/api/chat/sessions/${enc(sessionId)}/messages/${enc(messageId)}/edits/export?document_id=${enc(documentId)}`,
    { method: 'POST' },
  )
}

export type StreamHandlers = {
  onDelta: (text: string) => void
  /** Verified answer text that replaces everything streamed so far. */
  onFinalText?: (text: string) => void
  onEvent: (event: ChatEvent) => void
  onCitation: (citation: Citation) => void
  onTitle: (title: string) => void
  onError: (message: string) => void
  /** Server id of the assistant message being written (needed to save edit decisions). */
  onStart?: (assistantMessageId: string) => void
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
  options?: { mode?: WorkMode; files?: Attachment[] },
): Promise<void> {
  const res = await fetch(`/api/chat/sessions/${enc(sessionId)}/messages`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ content, mode: options?.mode, files: options?.files?.length ? options.files : undefined }),
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
        case 'text_final':
          handlers.onFinalText?.(String(event.text ?? ''))
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
          if (typeof event.assistant_message_id === 'string') handlers.onStart?.(event.assistant_message_id)
          break
        case 'done':
          break
        default:
          handlers.onEvent(event)
      }
    }
  }
}
