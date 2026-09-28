import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ApiError, apiFetch, authHeaders } from './client'
import { useApp } from '@/context/AppContext'

// Mirrors app/firm (plan 17, P2): matters, staffing, timeline, arguments, related matters,
// conflict checks and client intake, people, live updates, my work.

const enc = encodeURIComponent
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

/** The server's message for a refused write (`{detail: {message}}` or a plain detail). */
export function firmError(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const detail = (JSON.parse(err.body) as { detail?: unknown }).detail
      if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
      if (typeof detail === 'string') return detail
      if (Array.isArray(detail)) return 'Some fields are missing or invalid'
    } catch {
      // not JSON
    }
  }
  return err instanceof Error ? err.message : String(err)
}

// ── matters ──────────────────────────────────────────────────────────────────

export type MatterInput = {
  title: string
  client_id: string
  practice_area: string
  matter_type?: string
  matter_code?: string
  opposing_party?: string
  jurisdiction?: string
  court?: string
  office?: string
  access_mode?: 'open' | 'team' | 'restricted'
  lead_member_id?: string
  team?: { member_id: string; role: string }[]
  legal_issues?: string[]
  facts?: string[]
}
export type MatterBrief = { matter_id: string; matter_code: string; title: string; status: string; row_version: number; access_mode: string }

export const ROLES = ['Lead', 'Counsel', 'Associate', 'Junior', 'Paralegal', 'Knowledge Manager'] as const
export const EVENT_KINDS = ['event', 'filing', 'hearing', 'order', 'correspondence', 'meeting', 'milestone'] as const
export const RELATIONS = ['related', 'follow_up_to', 'parallel_proceeding', 'appeal_of', 'same_transaction', 'precedent_for'] as const

export const createMatter = (body: MatterInput) => apiFetch<MatterBrief>('/api/matters', json('POST', body))
export const updateMatter = (id: string, changes: Record<string, unknown>, rowVersion?: number) =>
  apiFetch<MatterBrief>(`/api/matters/${enc(id)}`, json('PATCH', { changes, row_version: rowVersion }))
export const setStaff = (id: string, memberId: string, body: { role: string; started_at?: string | null; ended_at?: string | null }) =>
  apiFetch(`/api/matters/${enc(id)}/team/${enc(memberId)}`, json('PUT', body))
export const removeStaff = (id: string, memberId: string) => apiFetch(`/api/matters/${enc(id)}/team/${enc(memberId)}`, json('DELETE'))

export type EventInput = { occurred_on?: string; title?: string; detail?: string; kind?: string; source_document_id?: string; row_version?: number }
export const addEvent = (id: string, body: EventInput) => apiFetch(`/api/matters/${enc(id)}/events`, json('POST', body))
export const updateEvent = (id: string, eventId: string, body: EventInput) =>
  apiFetch(`/api/matters/${enc(id)}/events/${enc(eventId)}`, json('PATCH', body))
export const deleteEvent = (id: string, eventId: string) => apiFetch(`/api/matters/${enc(id)}/events/${enc(eventId)}`, json('DELETE'))

export type ArgumentInput = { issue?: string; position?: string; argument?: string; outcome?: string; row_version?: number }
export const addArgument = (id: string, body: ArgumentInput) => apiFetch(`/api/matters/${enc(id)}/arguments`, json('POST', body))
export const updateArgument = (id: string, argId: string, body: ArgumentInput) =>
  apiFetch(`/api/matters/${enc(id)}/arguments/${enc(argId)}`, json('PATCH', body))
export const deleteArgument = (id: string, argId: string) => apiFetch(`/api/matters/${enc(id)}/arguments/${enc(argId)}`, json('DELETE'))

export const linkMatter = (id: string, related: string, relation: string, note: string) =>
  apiFetch(`/api/matters/${enc(id)}/related`, json('POST', { related_matter_id: related, relation, note }))
export const unlinkMatter = (id: string, related: string) => apiFetch(`/api/matters/${enc(id)}/related/${enc(related)}`, json('DELETE'))

// ── conflicts and clients ────────────────────────────────────────────────────

export type ConflictHit =
  | { kind: 'existing_client'; query: string; client_id: string; name: string; status: string; score: number }
  | { kind: 'adverse_party'; query: string; matter_id: string; matter_code: string; title: string; opposing_party: string; client_name: string; score: number; redacted?: false }
  | { kind: 'adverse_party'; query: string; redacted: true; note: string }
export type ConflictCheck = {
  check_id: string
  names: string[]
  purpose: string
  requested_by: string | null
  requested_at: string
  decision: 'clear' | 'conflict' | 'waived' | null
  decided_by: string | null
  decided_at: string | null
  notes: string
  status: 'clear' | 'conflict' | 'waived' | 'awaiting_risk'
  results: ConflictHit[]
}
export const runConflictCheck = (names: string[], purpose = '') => apiFetch<ConflictCheck>('/api/conflicts/check', json('POST', { names, purpose }))
export const listConflictChecks = (scope: 'mine' | 'to_decide') =>
  apiFetch<{ items: ConflictCheck[] }>(`/api/conflicts?scope=${scope}`).then((r) => r.items)
export const decideConflict = (checkId: string, decision: 'clear' | 'conflict' | 'waived', notes: string) =>
  apiFetch<ConflictCheck>(`/api/conflicts/${enc(checkId)}/decision`, json('POST', { decision, notes }))
export const createClient = (body: { name: string; check_id: string; industry?: string; headquarters?: string; aliases?: string[]; subsidiaries?: string[] }) =>
  apiFetch<{ client_id: string; name: string; status: string }>('/api/clients', json('POST', body))

// ── people ───────────────────────────────────────────────────────────────────

export type PersonInput = { name?: string; role?: string; office?: string; email?: string; is_lawyer?: boolean; practice_areas?: string[]; specializations?: string[]; roles?: string[] }
export const updateMe = (body: Pick<PersonInput, 'practice_areas' | 'specializations'>) => apiFetch('/api/people/me', json('PATCH', body))
export const createPerson = (body: PersonInput) => apiFetch<{ member_id: string; name: string }>('/api/people', json('POST', body))
export const updatePerson = (id: string, body: PersonInput) => apiFetch(`/api/people/${enc(id)}`, json('PATCH', body))

// ── my work ──────────────────────────────────────────────────────────────────

export type MyWork = {
  matters: { matter_id: string; matter_code: string; title: string; client_name: string | null; status: string; role_on_matter: string; next_due: string | null }[]
  due: { deadline_id: string; matter_id: string; matter_code: string; title: string; kind: string; due_date: string; overdue: boolean }[]
  editing: { document_id: string; title: string; state: 'editing' | 'draft'; at: string }[]
  comments: { comment_id: string; document_id: string; title: string; body: string; author_name: string | null; created_at: string; why: 'reply' | 'on_your_document' }[]
  decisions: {
    access_requests: { request_id: string; matter_id: string; matter_code: string; requester_name?: string; level: string }[]
    conflict_checks: { check_id: string; names: string[]; requested_at: string }[]
  }
}
export const getMyWork = () => apiFetch<MyWork>('/api/home/my-work')

// ── live updates ─────────────────────────────────────────────────────────────

export type DomainEvent = { seq: number; topic: string; entity_type: string; entity_id: string; matter_id: string | null; document_id: string | null; actor: string | null }

/** Query keys (after the identity prefix) that an event makes stale. */
function staleKeys(e: DomainEvent): unknown[][] {
  const keys: unknown[][] = []
  if (e.matter_id) keys.push(['matter', e.matter_id])
  if (e.topic.startsWith('matter.')) keys.push(['matters'], ['home'], ['my-work'])
  if (e.topic.startsWith('client.')) keys.push(['clients'])
  if (e.topic.startsWith('conflict.')) keys.push(['conflicts'], ['my-work'])
  if (e.topic.startsWith('person.')) keys.push(['people'], ['person', e.entity_id])
  return keys
}

/**
 * Follow the server's event stream (fetch-based: EventSource cannot send auth headers)
 * and refresh the affected queries. Reconnects with the last event id it saw.
 */
export function useLiveEvents() {
  const { identityKey } = useApp()
  const queryClient = useQueryClient()
  useEffect(() => {
    if (!identityKey) return
    const ctrl = new AbortController()
    let last: number | null = null
    let stopped = false
    const run = async () => {
      while (!stopped) {
        try {
          const url = `/api/events/stream${last !== null ? `?since=${last}` : ''}`
          const res = await fetch(url, { headers: authHeaders(), signal: ctrl.signal, credentials: 'same-origin' })
          if (!res.ok || !res.body) throw new Error(`stream ${res.status}`)
          const reader = res.body.getReader()
          const decoder = new TextDecoder()
          let buf = ''
          for (;;) {
            const { value, done } = await reader.read()
            if (done) break
            buf += decoder.decode(value, { stream: true })
            let cut: number
            while ((cut = buf.indexOf('\n\n')) >= 0) {
              const block = buf.slice(0, cut)
              buf = buf.slice(cut + 2)
              const data = block.split('\n').find((l) => l.startsWith('data: '))?.slice(6)
              const event = block.split('\n').find((l) => l.startsWith('event: '))?.slice(7)
              if (!data) continue
              const parsed = JSON.parse(data) as DomainEvent & { latest?: number }
              if (event === 'ready') {
                if (last === null && typeof parsed.latest === 'number') last = parsed.latest
                continue
              }
              last = parsed.seq
              for (const key of staleKeys(parsed)) void queryClient.invalidateQueries({ queryKey: [identityKey, ...key] })
              window.dispatchEvent(new CustomEvent('precentis:event', { detail: parsed }))
            }
          }
        } catch {
          if (ctrl.signal.aborted) return
          await new Promise((r) => setTimeout(r, 3000))
        }
      }
    }
    void run()
    return () => {
      stopped = true
      ctrl.abort()
    }
  }, [identityKey, queryClient])
}
