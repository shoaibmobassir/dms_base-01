import { useEffect, useState } from 'react'
import { ApiError, apiFetch, authHeaders } from './client'
import type { AskScopeType } from './resources'
import type { AskHistoryItem, AskResult } from './types'

/** Evidence the server gathered before the model starts writing. */
export type AskEvidence = {
  resolved_scope?: AskResult['resolved_scope']
  people?: Array<Record<string, unknown>>
  matter_cards?: AskResult['matter_cards']
  panel?: AskResult['panel']
  sources?: Array<Record<string, unknown>>
  saved?: boolean
}

export type AskStreamState = {
  phase: 'idle' | 'gathering' | 'writing' | 'verifying' | 'done' | 'error'
  evidence: AskEvidence | null
  keyFinding: string
  text: string
  result: AskResult | null
  error: string | null
  /** True when the shown answer came from storage, not a fresh model run. */
  fromCache: boolean
}

const INITIAL: AskStreamState = {
  phase: 'idle', evidence: null, keyFinding: '', text: '', result: null, error: null, fromCache: false,
}

type AskEvent =
  | ({ type: 'evidence' } & AskEvidence)
  | { type: 'key_finding'; status: string; text: string }
  | { type: 'delta'; text: string }
  | { type: 'verifying' }
  | { type: 'final'; result: AskResult; replaced: boolean; saved?: boolean }
  | { type: 'error'; message: string }

function scopeQuery(scope: { type: AskScopeType; value: string } | null | undefined) {
  if (!scope?.value) return ''
  const params = new URLSearchParams({ scope: scope.value, scopeType: scope.type })
  return `&${params.toString()}`
}

function savedToState(saved: AskResult): AskStreamState {
  return {
    phase: 'done',
    evidence: {
      resolved_scope: saved.resolved_scope,
      people: saved.people,
      matter_cards: saved.matter_cards,
      panel: saved.panel,
      sources: saved.sources,
      saved: true,
    },
    keyFinding: String(saved.key_finding ?? ''),
    text: String(saved.answer ?? ''),
    result: saved,
    error: null,
    fromCache: true,
  }
}

/** GET /api/answers/saved/{id} — reopen by answer id (like a chat session). */
export async function getSavedAskById(answerId: string, signal?: AbortSignal): Promise<AskResult | null> {
  try {
    return await apiFetch<AskResult>(`/api/answers/saved/${encodeURIComponent(answerId)}`, { signal })
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

/** GET /api/answers/saved?q= — legacy lookup by question text. */
export async function getSavedAsk(
  query: string,
  scope: { type: AskScopeType; value: string } | null,
  signal?: AbortSignal,
): Promise<AskResult | null> {
  const url = `/api/answers/saved?q=${encodeURIComponent(query)}${scopeQuery(scope)}`
  try {
    return await apiFetch<AskResult>(url, { signal })
  } catch (err) {
    if (err instanceof ApiError && err.status === 404) return null
    throw err
  }
}

/** POST /api/answers/stream and report each server-sent event. */
export async function streamAsk(
  body: { query: string; scope?: { type: AskScopeType; value: string } | null; refresh?: boolean },
  onEvent: (event: AskEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/answers/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({
      query: body.query,
      k: 10,
      refresh: !!body.refresh,
      ...(body.scope?.value ? { scope: body.scope } : {}),
    }),
    signal,
  })
  if (!res.ok || !res.body) throw new ApiError(res.status, await res.text())
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
      try {
        onEvent(JSON.parse(data) as AskEvent)
      } catch {
        // partial or malformed chunk
      }
    }
  }
}

export type UseAskArgs = {
  /** Saved answer id from the URL (`/ask/:answerId`). */
  answerId?: string | null
  /** Fresh question from `?q=` (runs once, then the page should navigate to the saved id). */
  query?: string | null
  scope?: { type: AskScopeType; value: string } | null
  /** >0 forces a model refresh for the current question. */
  runKey?: number
  /** Called when a fresh ask finishes and the server returns a stable saved id. */
  onSaved?: (savedId: string, result: AskResult) => void
}

/**
 * Open by answer id (no model), or run a new question once and hand the saved id back.
 */
export function useAskStream({ answerId = null, query = null, scope = null, runKey = 0, onSaved }: UseAskArgs) {
  const [state, setState] = useState<AskStreamState>(INITIAL)
  const scopeType = scope?.type ?? null
  const scopeValue = scope?.value ?? null

  useEffect(() => {
    if (!answerId && !query) {
      setState(INITIAL)
      return
    }
    const controller = new AbortController()
    setState({ ...INITIAL, phase: 'gathering' })
    const scopeArg = scopeValue ? { type: scopeType ?? 'auto', value: scopeValue } : null
    const refresh = runKey > 0

    const applyEvent = (event: AskEvent) => {
      if (event.type === 'final') {
        const id = typeof event.result?.saved_id === 'string' ? event.result.saved_id : null
        if (id) onSaved?.(id, event.result)
      }
      setState((prev) => {
        switch (event.type) {
          case 'evidence':
            return { ...prev, evidence: event, fromCache: !!event.saved }
          case 'key_finding':
            return { ...prev, phase: 'writing', keyFinding: event.text }
          case 'delta':
            return { ...prev, phase: 'writing', text: prev.text + event.text }
          case 'verifying':
            return { ...prev, phase: 'verifying' }
          case 'final':
            return {
              ...prev,
              phase: 'done',
              result: event.result,
              fromCache: !!event.saved || !!event.result?.saved,
            }
          case 'error':
            return { ...prev, phase: 'error', error: event.message }
          default:
            return prev
        }
      })
    }

    const run = async () => {
      // Prefer the session-style id: load the stored payload and stop.
      if (answerId && !refresh) {
        const saved = await getSavedAskById(answerId, controller.signal)
        if (controller.signal.aborted) return
        if (saved) {
          setState(savedToState(saved))
          return
        }
        setState({
          ...INITIAL,
          phase: 'error',
          error: 'That Ask answer is not available.',
        })
        return
      }

      const askQuery = query
      if (!askQuery && answerId) {
        const existing = await getSavedAskById(answerId, controller.signal)
        if (controller.signal.aborted) return
        const storedQuery = existing ? String(existing.query || '') : ''
        if (!storedQuery) {
          setState({ ...INITIAL, phase: 'error', error: 'That Ask answer is not available.' })
          return
        }
        await streamAsk(
          {
            query: storedQuery,
            scope: existing?.scope
              ? { type: (existing.scope_type as AskScopeType) || 'auto', value: String(existing.scope) }
              : scopeArg,
            refresh: true,
          },
          applyEvent,
          controller.signal,
        )
        return
      }
      if (!askQuery) {
        setState(INITIAL)
        return
      }

      if (!refresh && !answerId) {
        try {
          const saved = await getSavedAsk(askQuery, scopeArg, controller.signal)
          if (controller.signal.aborted) return
          if (saved) {
            setState(savedToState(saved))
            const id = typeof saved.saved_id === 'string' ? saved.saved_id : null
            if (id) onSaved?.(id, saved)
            return
          }
        } catch {
          // Fall through to streaming.
        }
      }

      await streamAsk(
        { query: askQuery, scope: scopeArg, refresh },
        applyEvent,
        controller.signal,
      )
    }

    run().catch((err: unknown) => {
      if (controller.signal.aborted) return
      setState((prev) => ({ ...prev, phase: 'error', error: err instanceof Error ? err.message : String(err) }))
    })
    return () => controller.abort()
    // Intentionally omit onSaved — callers pass stable callbacks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [answerId, query, scopeType, scopeValue, runKey])

  return state
}

// ── recent questions ─────────────────────────────────────────────────────────

export function listAskHistory(limit = 30) {
  return apiFetch<{ items: AskHistoryItem[] }>(`/api/answers/history?limit=${limit}`)
}

export function deleteAskHistory(id?: string) {
  return apiFetch<void>(id ? `/api/answers/history/${encodeURIComponent(id)}` : '/api/answers/history', { method: 'DELETE' })
}
