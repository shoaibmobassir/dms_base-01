import { useQuery } from '@tanstack/react-query'
import { useApp } from '@/context/AppContext'
import { apiFetch, downloadFile, qs } from './client'
import type { WorkspaceKind } from './workspaces'

// Mirrors app/tabular (plan 22, W4): durable reviews of many documents × many questions.

const enc = encodeURIComponent
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export type AnswerFormat = 'text' | 'date' | 'yes_no' | 'number' | 'money' | 'list' | 'choice'
export const FORMAT_LABEL: Record<AnswerFormat, string> = {
  text: 'Text', date: 'Date', yes_no: 'Yes / no', number: 'Number', money: 'Amount', list: 'List', choice: 'Choice',
}

export type ReviewColumn = { column_id: string; position: number; label: string; question: string; answer_format: AnswerFormat; choices: string[]; revision: number }
export type ReviewRow = {
  row_id: string; position: number; kind: 'document' | 'folder'; document_id: string | null; folder_path: string | null
  title: string | null; mime_type: string | null; restricted: boolean; running: boolean
}
export type Citation = { document_id: string | null; chunk_id: string | null; page: number | null; quote: string; verified: boolean }
export type CellStatus = 'pending' | 'running' | 'done' | 'not_found' | 'failed' | 'stale'
export type ReviewCell = {
  row_id: string; column_id: string; status: CellStatus; stale: boolean; restricted: boolean; updated_at: string
  answer?: string | null; citations?: Citation[]; error?: string | null; edited?: boolean; edited_by?: string | null; model_answer?: string | null
}
export type Review = {
  review_id: string; title: string; container_kind: WorkspaceKind; container_id: string; group_by: 'document' | 'folder'
  owner_member_id: string | null; created_at: string; updated_at: string; row_version: number; my_level: 'read' | 'edit' | 'manage'
  archived_at: string | null
  columns: ReviewColumn[]; rows: ReviewRow[]; cells: ReviewCell[]; counts: Partial<Record<CellStatus, number>>; running: boolean
}
export type ReviewSummary = {
  review_id: string; title: string; group_by: string; created_at: string; updated_at: string; owner_name: string | null
  row_count: number; column_count: number; open_cells: number
}
export type Preset = { key: string; label: string; question: string; answer_format: AnswerFormat }
export type ColumnInput = { label?: string; question?: string; answer_format?: AnswerFormat; choices?: string[]; preset?: string }

export const useReviews = (kind: WorkspaceKind, id: string) => {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, 'tab-reviews', kind, id],
    queryFn: () => apiFetch<{ items: ReviewSummary[] }>(`/api/tabular/reviews${qs({ kind, id })}`).then((r) => r.items),
    enabled: identityKey !== null && !!id,
  })
}

/** A review, polled while cells are being filled. */
export const useReview = (reviewId: string) => {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, 'tab-review', reviewId],
    queryFn: () => apiFetch<Review>(`/api/tabular/reviews/${enc(reviewId)}`),
    enabled: identityKey !== null && !!reviewId,
    refetchInterval: (q) => {
      const d = q.state.data
      return d && (d.running || (d.counts.pending ?? 0) > 0 || (d.counts.running ?? 0) > 0) ? 1500 : false
    },
  })
}

export const usePresets = () =>
  useQuery({ queryKey: ['tab-presets'], queryFn: () => apiFetch<{ presets: Preset[] }>('/api/tabular/presets').then((r) => r.presets), staleTime: Infinity })

export const createReview = (body: {
  title: string; kind: WorkspaceKind; id: string; columns: ColumnInput[]; document_ids?: string[]; folders?: string[]
  group_by?: 'document' | 'folder'; run?: boolean; playbook_id?: string
}) => apiFetch<Review>('/api/tabular/reviews', json('POST', body))

export const runReview = (id: string, body: { scope: 'open' | 'all' | 'column' | 'row' | 'cell'; column_id?: string; row_id?: string }) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/run`, json('POST', body))
export const renameReview = (id: string, title: string, row_version?: number) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}`, json('PATCH', { title, row_version }))
export const archiveReview = (id: string) => apiFetch(`/api/tabular/reviews/${enc(id)}`, json('DELETE'))
export const addColumns = (id: string, columns: ColumnInput[]) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/columns`, json('POST', columns))
export const updateColumn = (id: string, columnId: string, changes: Partial<ColumnInput> & { position?: number }) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/columns/${enc(columnId)}`, json('PATCH', changes))
export const deleteColumn = (id: string, columnId: string) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/columns/${enc(columnId)}`, json('DELETE'))
export const addRows = (id: string, body: { document_ids?: string[]; folders?: string[] }) =>
  apiFetch<Review & { added: number }>(`/api/tabular/reviews/${enc(id)}/rows`, json('POST', body))
export const deleteRow = (id: string, rowId: string) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/rows/${enc(rowId)}`, json('DELETE'))
export const overrideCell = (id: string, rowId: string, columnId: string, answer: string | null) =>
  apiFetch<Review>(`/api/tabular/reviews/${enc(id)}/cells/${enc(rowId)}/${enc(columnId)}`, json('PATCH', { answer }))
export const exportReview = (id: string, title: string) => downloadFile(`/api/tabular/reviews/${enc(id)}/export.xlsx`, `${title}.xlsx`)
