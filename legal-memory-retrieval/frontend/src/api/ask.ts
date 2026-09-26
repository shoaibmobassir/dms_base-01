import { useEffect, useState } from 'react'
import { ApiError, authHeaders } from './client'
import type { AskScopeType } from './resources'
import type { AskResult } from './types'

/** Evidence the server gathered before the model starts writing. */
export type AskEvidence = {
  resolved_scope?: AskResult['resolved_scope']
  people?: Array<Record<string, unknown>>
  matter_cards?: Array<Record<string, unknown>>
  sources?: Array<Record<string, unknown>>
}

export type AskStreamState = {
  phase: 'idle' | 'gathering' | 'writing' | 'done' | 'error'
  evidence: AskEvidence | null
  keyFinding: string
  text: string
  result: AskResult | null
  error: string | null
}

const INITIAL: AskStreamState = { phase: 'idle', evidence: null, keyFinding: '', text: '', result: null, error: null }

type AskEvent =
  | ({ type: 'evidence' } & AskEvidence)
  | { type: 'key_finding'; status: string; text: string }
  | { type: 'delta'; text: string }
  | { type: 'final'; result: AskResult; replaced: boolean }
  | { type: 'error'; message: string }

/** POST /api/answers/stream and report each server-sent event. */
export async function streamAsk(
  body: { query: string; scope?: { type: AskScopeType; value: string } | null },
  onEvent: (event: AskEvent) => void,
  signal: AbortSignal,
): Promise<void> {
  const res = await fetch('/api/answers/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ query: body.query, k: 10, ...(body.scope?.value ? { scope: body.scope } : {}) }),
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

/** Stream an Ask the Firm answer; restarts when the question or scope changes. */
export function useAskStream(query: string | null, scope: { type: AskScopeType; value: string } | null, runKey = 0) {
  const [state, setState] = useState<AskStreamState>(INITIAL)
  const scopeType = scope?.type ?? null
  const scopeValue = scope?.value ?? null

  useEffect(() => {
    if (!query) {
      setState(INITIAL)
      return
    }
    const controller = new AbortController()
    setState({ ...INITIAL, phase: 'gathering' })
    const scopeArg = scopeValue ? { type: scopeType ?? 'auto', value: scopeValue } : null
    streamAsk(
      { query, scope: scopeArg },
      (event) => {
        setState((prev) => {
          switch (event.type) {
            case 'evidence':
              return { ...prev, evidence: event }
            case 'key_finding':
              return { ...prev, phase: 'writing', keyFinding: event.text }
            case 'delta':
              return { ...prev, phase: 'writing', text: prev.text + event.text }
            case 'final':
              return { ...prev, phase: 'done', result: event.result }
            case 'error':
              return { ...prev, phase: 'error', error: event.message }
            default:
              return prev
          }
        })
      },
      controller.signal,
    ).catch((err: unknown) => {
      if (controller.signal.aborted) return
      setState((prev) => ({ ...prev, phase: 'error', error: err instanceof Error ? err.message : String(err) }))
    })
    return () => controller.abort()
  }, [query, scopeType, scopeValue, runKey])

  return state
}
