import { useQuery } from '@tanstack/react-query'
import { useApp } from '@/context/AppContext'
import { apiFetch, qs } from './client'
import type { AnswerFormat } from './tabular'

// Mirrors app/playbooks (plan 22, W5).

const enc = encodeURIComponent
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export type PlaybookKind = 'instructions' | 'columns'
export type PlaybookSource = 'shipped' | 'firm' | 'personal'
export type PlaybookColumn = { label: string; question: string; answer_format: AnswerFormat; choices: string[] }
export type PlaybookSummary = {
  playbook_id: string; kind: PlaybookKind; source: PlaybookSource; title: string; summary: string | null
  practice_area: string | null; jurisdiction: string | null; language: string | null; owner_member_id: string | null
  origin_playbook_id: string | null; version: number; row_version: number; updated_at: string
  my_level: 'read' | 'edit' | 'manage'; column_count: number
}
export type Playbook = PlaybookSummary & {
  body_md: string; columns: PlaybookColumn[]; files: { document_id: string; title: string }[]
  shares: { principal_type: 'member' | 'team'; principal_id: string; level: 'view' | 'edit'; name: string | null }[]
}
export type PlaybookInput = {
  kind: PlaybookKind; title: string; summary?: string; practice_area?: string; jurisdiction?: string; language?: string
  body_md?: string; columns?: PlaybookColumn[]; document_ids?: string[]
}

export const SOURCE_LABEL: Record<PlaybookSource, string> = { shipped: 'Built in', firm: 'Firm', personal: 'Mine' }

export const usePlaybooks = (p: { kind?: PlaybookKind; q?: string; enabled?: boolean } = {}) => {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, 'playbooks', p.kind ?? '', p.q ?? ''],
    queryFn: () => apiFetch<{ items: PlaybookSummary[] }>(`/api/playbooks${qs({ kind: p.kind, q: p.q })}`).then((r) => r.items),
    enabled: identityKey !== null && p.enabled !== false,
  })
}

export const usePlaybook = (id: string | null) => {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, 'playbook', id],
    queryFn: () => apiFetch<Playbook>(`/api/playbooks/${enc(id!)}`),
    enabled: identityKey !== null && !!id,
  })
}

export const createPlaybook = (body: PlaybookInput) => apiFetch<Playbook>('/api/playbooks', json('POST', body))
export const updatePlaybook = (id: string, body: Partial<PlaybookInput> & { row_version?: number }) =>
  apiFetch<Playbook>(`/api/playbooks/${enc(id)}`, json('PATCH', body))
export const duplicatePlaybook = (id: string) => apiFetch<Playbook>(`/api/playbooks/${enc(id)}/duplicate`, json('POST'))
export const publishPlaybook = (id: string) => apiFetch<Playbook>(`/api/playbooks/${enc(id)}/publish`, json('POST'))
export const sharePlaybook = (id: string, body: { principal_type: 'member' | 'team'; principal_id: string; level: 'view' | 'edit' | null }) =>
  apiFetch<Playbook>(`/api/playbooks/${enc(id)}/shares`, json('PUT', body))
export const archivePlaybook = (id: string) => apiFetch(`/api/playbooks/${enc(id)}`, json('DELETE'))
export const saveReviewAsPlaybook = (reviewId: string, title?: string) =>
  apiFetch<Playbook>(`/api/tabular/reviews/${enc(reviewId)}/save-as-playbook`, json('POST', { title }))
