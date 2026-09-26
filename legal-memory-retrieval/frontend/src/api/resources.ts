import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useApp } from '@/context/AppContext'
import { apiFetch, qs } from './client'
import type {
  ArgumentItem,
  ChatSession,
  ClientDetail,
  ClientItem,
  Deadline,
  DocumentBlock,
  DocumentChunk,
  DocumentDetail,
  DocumentItem,
  DocumentOutlineItem,
  DocVersion,
  HomeStats,
  Matter,
  MatterArgument,
  MatterDetail,
  Paged,
  Person,
  PersonDetail,
  RelatedMatter,
  SearchResult,
  SystemInfo,
  Team,
  TimelineEvent,
} from './types'

export const PAGE_SIZE = 50

const enc = encodeURIComponent

// Every query key starts with the caller so switching persona never shows
// another member's cached (ACL-filtered) data.
function useScopedQuery<T>(
  key: unknown[],
  fn: () => Promise<T>,
  enabled = true,
  opts: { once?: boolean } = {},
) {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, ...key],
    queryFn: fn,
    enabled: enabled && identityKey !== null,
    // Lists keep showing the previous page while the next one loads. One-shot
    // queries (Ask runs the LLM) never refetch and never show stale answers.
    placeholderData: opts.once ? undefined : keepPreviousData,
    staleTime: opts.once ? Infinity : undefined,
    retry: opts.once ? false : undefined,
  })
}

// ── Home ──────────────────────────────────────────────────────────────────
export const useHomeStats = () => useScopedQuery(['home'], () => apiFetch<HomeStats>('/api/home/stats'))

// ── Matters ───────────────────────────────────────────────────────────────
export function useMatters(p: { q?: string; status?: string; page?: number; limit?: number }) {
  const limit = p.limit ?? PAGE_SIZE
  const offset = (p.page ?? 0) * limit
  return useScopedQuery(['matters', p.q, p.status, offset, limit], () =>
    apiFetch<Paged<Matter>>(`/api/matters${qs({ q: p.q, status: p.status, limit, offset })}`),
  )
}

export const useMatter = (id: string) =>
  useScopedQuery(['matter', id], () => apiFetch<MatterDetail>(`/api/matters/${enc(id)}`), !!id)

export const useMatterTimeline = (id: string) =>
  useScopedQuery(['matter', id, 'timeline'], () =>
    apiFetch<{ timeline: TimelineEvent[] }>(`/api/matters/${enc(id)}/timeline`).then((r) => r.timeline),
  )

export const useMatterArguments = (id: string) =>
  useScopedQuery(['matter', id, 'arguments'], () =>
    apiFetch<{ arguments: MatterArgument[] }>(`/api/matters/${enc(id)}/arguments`).then((r) => r.arguments),
  )

export const useMatterRelated = (id: string) =>
  useScopedQuery(['matter', id, 'related'], () =>
    apiFetch<{ related: RelatedMatter[] }>(`/api/matters/${enc(id)}/related`).then((r) => r.related),
  )

// ── Documents ─────────────────────────────────────────────────────────────
export function useDocuments(p: { q?: string; matter_id?: string; page?: number; limit?: number }) {
  const limit = p.limit ?? PAGE_SIZE
  const offset = (p.page ?? 0) * limit
  return useScopedQuery(['documents', p.q, p.matter_id, offset, limit], () =>
    apiFetch<Paged<DocumentItem>>(
      `/api/documents${qs({ q: p.q, matter_id: p.matter_id, limit, offset })}`,
    ),
  )
}

export const useDocument = (id: string, opts?: { q?: string; chunk_id?: string; lean?: boolean }) =>
  useScopedQuery(['document', id, opts?.q, opts?.chunk_id, opts?.lean ?? false], () =>
    apiFetch<DocumentDetail>(
      `/api/documents/${enc(id)}${qs({ q: opts?.q, chunk_id: opts?.chunk_id, lean: opts?.lean ? 'true' : undefined })}`,
    ),
    !!id,
  )

export const useDocumentVersions = (id: string) =>
  useScopedQuery(['document', id, 'versions'], () =>
    apiFetch<{ versions: DocVersion[] }>(`/api/documents/${enc(id)}/versions`).then((r) => r.versions),
  )

export function useDocumentOutline(documentId: string, versionId: string | undefined) {
  return useScopedQuery(
    ['document', documentId, 'outline', versionId],
    () =>
      apiFetch<{ outline: DocumentOutlineItem[]; outline_source: string | null }>(
        `/api/documents/${enc(documentId)}/versions/${enc(versionId!)}/outline`,
      ),
    !!documentId && !!versionId,
  )
}

export function useDocumentChunks(
  documentId: string,
  opts: { offset: number; limit: number; enabled?: boolean },
) {
  return useScopedQuery(
    ['document', documentId, 'chunks', opts.offset, opts.limit],
    () =>
      apiFetch<{ chunks: DocumentChunk[]; total: number; offset: number; limit: number }>(
        `/api/documents/${enc(documentId)}/chunks${qs({ offset: opts.offset, limit: opts.limit })}`,
      ),
    !!documentId && (opts.enabled ?? true),
  )
}

export function useDocumentBlocks(
  documentId: string,
  versionId: string | undefined,
  opts: { from: number; limit: number; enabled?: boolean },
) {
  return useScopedQuery(
    ['document', documentId, 'blocks', versionId, opts.from, opts.limit],
    () =>
      apiFetch<{ blocks: DocumentBlock[]; total: number; from: number; limit: number }>(
        `/api/documents/${enc(documentId)}/versions/${enc(versionId!)}/blocks${qs({
          from: opts.from,
          limit: opts.limit,
        })}`,
      ),
    !!documentId && !!versionId && (opts.enabled ?? true),
  )
}

export function compareVersions(documentId: string, versionId: string, compareWith: string) {
  return apiFetch<{ diff?: string }>(
    `/api/documents/${enc(documentId)}/versions/${enc(versionId)}/diff${qs({ compare_with: compareWith })}`,
  )
}

export function ingestDocument(body: { title: string; matter_id: string; body: string; document_type: string }) {
  return apiFetch<{ document_id?: string; chunks_indexed?: number }>('/api/documents/ingest', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ── Clients ───────────────────────────────────────────────────────────────
export function useClients(p: { q?: string; page?: number }) {
  const offset = (p.page ?? 0) * PAGE_SIZE
  return useScopedQuery(['clients', p.q, offset], () =>
    apiFetch<Paged<ClientItem>>(`/api/clients${qs({ q: p.q, limit: PAGE_SIZE, offset })}`),
  )
}

export const useClient = (id: string) =>
  useScopedQuery(['client', id], () => apiFetch<ClientDetail>(`/api/clients/${enc(id)}`), !!id)

// ── People ────────────────────────────────────────────────────────────────
export const usePeople = () =>
  useScopedQuery(['people'], () => apiFetch<{ items: Person[] }>('/api/people').then((r) => r.items))

export const usePerson = (id: string) =>
  useScopedQuery(['person', id], () => apiFetch<PersonDetail>(`/api/people/${enc(id)}`), !!id)

// ── Deadlines, arguments, teams ───────────────────────────────────────────
export const useDeadlines = (p: { status?: 'open' | 'done' | 'all'; matter_id?: string; limit?: number }) =>
  useScopedQuery(['deadlines', p.status, p.matter_id, p.limit], () =>
    apiFetch<{ items: Deadline[] }>(
      `/api/tasks${qs({ status: p.status, matter_id: p.matter_id, limit: p.limit ?? 100 })}`,
    ).then((r) => r.items),
  )

export function useArguments(p: { q?: string; page?: number }) {
  const offset = (p.page ?? 0) * PAGE_SIZE
  return useScopedQuery(['arguments', p.q, offset], () =>
    apiFetch<Paged<ArgumentItem>>(`/api/knowledge/arguments${qs({ q: p.q, limit: PAGE_SIZE, offset })}`),
  )
}

export const useTeams = () =>
  useScopedQuery(['teams'], () => apiFetch<{ items: Team[] }>('/api/teams').then((r) => r.items))

// ── Search, ask, system ───────────────────────────────────────────────────
export const useSearch = (q: string) =>
  useScopedQuery(
    ['search', q],
    () => apiFetch<{ results: SearchResult[] }>(`/api/search${qs({ q, limit: 20 })}`).then((r) => r.results),
    q.trim().length >= 2,
  )

export type AskScopeType = 'matter' | 'client' | 'auto'

export const useSystemInfo = () => useScopedQuery(['system-info'], () => apiFetch<SystemInfo>('/api/system/info'))

// ── Pins & recent conversations (sidebar) ─────────────────────────────────
export type PinnedMatter = Pick<Matter, 'matter_id' | 'matter_code' | 'title' | 'client_name' | 'status' | 'restricted'>

export const usePinnedMatters = () =>
  useScopedQuery(['pinned-matters'], () =>
    apiFetch<{ items: PinnedMatter[] }>('/api/matters/pinned').then((r) => r.items),
  )

export function setPinned(matterId: string, pinned: boolean) {
  return apiFetch<void>(`/api/matters/${enc(matterId)}/pin`, { method: pinned ? 'PUT' : 'DELETE' })
}

export const useRecentConversations = () =>
  useScopedQuery(['chat-sessions'], () => apiFetch<ChatSession[]>('/api/chat/sessions?limit=50'))
