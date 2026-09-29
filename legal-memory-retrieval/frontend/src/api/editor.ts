import { ApiError, apiFetch, authHeaders } from './client'

// Mirrors app/documents/editing.py and /api/editor (plan 16).

export type EditRun = { text: string; bold: boolean; italic: boolean; underline: boolean }
export type PendingAuthor = { author: string; types: string[]; count: number }
export type EditParagraph = {
  pid: number
  style: string
  text: string
  runs: EditRun[]
  /** Tracked changes still pending in this paragraph (Word review). */
  pending?: PendingAuthor[]
  /** Someone else's pending changes (or a pending deletion): accept/reject them before editing. */
  locked?: boolean
  locked_reason?: 'others' | 'deleted' | null
}
/** Formatting a paragraph asks for: its style, and its text split by bold/italic/underline. */
export type EditFormatting = { style?: string; runs?: EditRun[] }
export type EditOp =
  | ({ op: 'replace'; pid: number; text: string } & EditFormatting)
  | { op: 'delete'; pid: number }
  | ({ op: 'insert_after'; pid: number; text: string } & EditFormatting)
  | ({ op: 'format'; pid: number } & EditFormatting)

export type EditLock = { member_id: string; name: string; source: string; acquired_at?: string; expires_at: string; lock_token?: string }

export type EditModel = {
  document_id: string
  title: string
  matter_id: string
  mode: 'docx' | 'text' | 'pdf'
  editable: boolean
  base_version_id: string
  version_number: number | null
  has_revisions: boolean
  pending_changes?: number
  pending_people?: string[]
  paragraphs: EditParagraph[]
  /** Paragraph styles the editor may apply (those the Word file defines). */
  styles: string[]
  lock: EditLock | null
  draft: { base_version_id: string; ops: EditOp[]; updated_at: string } | null
}

export type SaveResult = { version_id: string; version_number: number; mode: 'tracked' | 'clean'; stats: Record<string, number> }

export type CompareBlock =
  | { op: 'equal'; count: number; from: number }
  | { op: 'replace'; old: string; new: string; segments: { t: 'eq' | 'ins' | 'del'; text: string }[] }
  | { op: 'delete'; old: string }
  | { op: 'insert'; new: string }

export type CompareResult = {
  document_id: string
  from: VersionMeta
  to: VersionMeta
  stats: { inserted: number; deleted: number; changed: number; unchanged: number }
  blocks: CompareBlock[]
}
export type VersionMeta = { version_id: string; version_number: number; author: string | null; created_at: string; note: string | null }

export type DocEvent = { seq: number; action: string; version_id: string | null; member_id: string | null; name: string | null; detail: Record<string, unknown>; occurred_at: string }

const base = (id: string) => `/api/editor/documents/${encodeURIComponent(id)}`
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

/** Error text from our `{detail: {message, ...}}` shape (or FastAPI's plain detail). */
export function editErrorMessage(err: unknown): string {
  if (err instanceof ApiError) {
    try {
      const detail = (JSON.parse(err.body) as { detail?: unknown }).detail
      if (detail && typeof detail === 'object' && 'message' in detail) return String((detail as { message: unknown }).message)
      if (typeof detail === 'string') return detail
    } catch {
      // not JSON
    }
  }
  return err instanceof Error ? err.message : String(err)
}

export type LockConflictReason = 'held' | 'held_by_you_elsewhere' | 'superseded'
export type EditConflict = { lock?: EditLock | null; current_version_id?: string; reason?: LockConflictReason; can_take_over?: boolean }

export function editConflict(err: unknown): EditConflict | null {
  if (!(err instanceof ApiError) || err.status !== 409) return null
  try {
    const detail = (JSON.parse(err.body) as { detail?: EditConflict }).detail
    return detail ?? {}
  } catch {
    return {}
  }
}

// ── the edit lock of this window ─────────────────────────────────────────────
// Each window holds its own lock token (sessionStorage survives a reload of the same
// window, not a second window) and sends it with every write, so a window that lost the
// lock to another window or person cannot overwrite anything.

const tokenKey = (id: string) => `precentis.editlock.${id}`
function lockToken(id: string): string | null {
  try {
    return sessionStorage.getItem(tokenKey(id))
  } catch {
    return null
  }
}
function setLockToken(id: string, token: string | null) {
  try {
    if (token) sessionStorage.setItem(tokenKey(id), token)
    else sessionStorage.removeItem(tokenKey(id))
  } catch {
    // storage unavailable: the lock still works for this page's lifetime via the server
  }
}
const lockHeaders = (id: string): Record<string, string> => {
  const token = lockToken(id)
  return token ? { 'X-Edit-Lock': token } : {}
}
const withLock = (id: string, init: RequestInit): RequestInit => ({ ...init, headers: { ...lockHeaders(id) } })

export const getEditModel = (id: string) => apiFetch<EditModel>(base(id))

export async function acquireLock(id: string, opts: { takeover?: boolean } = {}) {
  const lock = await apiFetch<EditLock>(`${base(id)}/lock${opts.takeover ? '?takeover=true' : ''}`, withLock(id, json('POST')))
  setLockToken(id, lock.lock_token ?? null)
  return lock
}
export const heartbeatLock = (id: string) => apiFetch<{ expires_at: string }>(`${base(id)}/lock/heartbeat`, withLock(id, json('POST')))
export async function releaseLock(id: string) {
  await apiFetch<void>(`${base(id)}/lock`, withLock(id, json('DELETE')))
  setLockToken(id, null)
}
/** Forget this window's token without releasing (the lock was taken over). */
export const forgetLock = (id: string) => setLockToken(id, null)

/** Release on page unload: keepalive lets the request outlive the page. The token stays in
 * sessionStorage so a reload of this window picks the lock up again if the release was lost. */
export function releaseLockOnUnload(id: string) {
  void fetch(`${base(id)}/lock`, {
    method: 'DELETE', headers: { ...authHeaders(), ...lockHeaders(id) }, keepalive: true, credentials: 'same-origin',
  })
}

export const putDraft = (id: string, baseVersionId: string, ops: EditOp[]) =>
  apiFetch<{ saved_at: string; ops: number }>(`${base(id)}/draft`, withLock(id, json('PUT', { base_version_id: baseVersionId, ops })))
export const deleteDraft = (id: string) => apiFetch<void>(`${base(id)}/draft`, json('DELETE'))

export const saveEdits = (id: string, body: { base_version_id: string; ops: EditOp[]; note: string; mode: 'tracked' | 'clean' }) =>
  apiFetch<SaveResult>(`${base(id)}/save`, withLock(id, json('POST', body)))

export const compareVersions = (id: string, from: string, to: string) =>
  apiFetch<CompareResult>(`${base(id)}/compare?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`)

export const compareDocxUrl = (id: string, from: string, to: string) =>
  `${base(id)}/compare.docx?from=${encodeURIComponent(from)}&to=${encodeURIComponent(to)}`

export const documentHistory = (id: string) => apiFetch<{ items: DocEvent[] }>(`${base(id)}/history`).then((r) => r.items)

/** Upload a file as the document's next version (multipart; apiFetch would force JSON). */
export async function uploadVersion(id: string, file: File, opts: { baseVersionId?: string; note?: string; label?: string }) {
  const form = new FormData()
  form.append('file', file)
  if (opts.baseVersionId) form.append('base_version_id', opts.baseVersionId)
  if (opts.note) form.append('note', opts.note)
  if (opts.label) form.append('label', opts.label)
  const res = await fetch(`${base(id)}/versions`, { method: 'POST', body: form, headers: { ...authHeaders(), ...lockHeaders(id) }, credentials: 'same-origin' })
  if (!res.ok) throw new ApiError(res.status, await res.text())
  return (await res.json()) as { version_id: string; version_number: number }
}

// ── comments on the exact view (E6) ──────────────────────────────────────────

/** An area of a page, as fractions of its width and height (0..1). */
export type PageBox = { x0: number; y0: number; x1: number; y1: number }

export type DocComment = {
  comment_id: string
  version_id: string
  version_number: number | null
  parent_id: string | null
  page: number
  rects: PageBox[]
  quote: string
  body: string
  author_id: string | null
  author: string | null
  /** "word": came from the Word file (author may be outside the firm). */
  source?: 'precentis' | 'word'
  status: 'open' | 'resolved'
  resolved_by: string | null
  resolved_at: string | null
  created_at: string
}
/** ``carried``: an open thread started on an earlier version, re-found here by its quote. */
export type CommentThread = DocComment & { carried: boolean; replies: DocComment[] }
export type CommentList = {
  document_id: string
  version_id: string
  version_number: number
  is_current: boolean
  threads: CommentThread[]
  on_other_versions: number
}

export const listComments = (id: string, versionId?: string) =>
  apiFetch<CommentList>(`${base(id)}/comments${versionId ? `?version_id=${encodeURIComponent(versionId)}` : ''}`)
export const addComment = (id: string, body: { body: string; version_id?: string; page?: number; rects?: PageBox[]; quote?: string; parent_id?: string }) =>
  apiFetch<DocComment>(`${base(id)}/comments`, json('POST', body))
export const setCommentStatus = (id: string, commentId: string, status: 'open' | 'resolved') =>
  apiFetch<DocComment>(`${base(id)}/comments/${encodeURIComponent(commentId)}`, json('PATCH', { status }))
export const deleteComment = (id: string, commentId: string) =>
  apiFetch<void>(`${base(id)}/comments/${encodeURIComponent(commentId)}`, json('DELETE'))

// ── document privacy (plan 17, P1b) ──────────────────────────────────────────

export type Visibility = 'matter' | 'private' | 'restricted'
export type DocShare = { principal_type: 'member' | 'team'; principal_id: string; level: 'read' | 'edit'; name?: string | null }
export type DocPrivacy = {
  document_id: string
  visibility: Visibility
  owner: { member_id: string; name: string } | null
  shares: DocShare[]
  row_version: number
  can_change: boolean
}
export type ShareTargets = {
  people: { member_id: string; name: string; role: string | null; office: string | null }[]
  teams: { team_id: string; name: string; members: number }[]
}

export const getPrivacy = (id: string) => apiFetch<DocPrivacy>(`${base(id)}/privacy`)
export const setPrivacy = (id: string, body: { visibility: Visibility; shares: DocShare[]; row_version: number }) =>
  apiFetch<DocPrivacy>(`${base(id)}/privacy`, json('PUT', body))
export const getShareTargets = (id: string) => apiFetch<ShareTargets>(`${base(id)}/share-targets`)

// ── Word review (plan 18) ────────────────────────────────────────────────────

export type ReviewChange = {
  id: string
  type: string
  author: string
  date: string | null
  last_date: string | null
  pid: number | null
  table: boolean
  keys: string[]
  texts: string[]
  detail: string
  context: string
  paragraph: boolean
}
export type ReviewPerson = {
  author: string
  member_id: string | null
  insertions: number
  deletions: number
  formats: number
  moves: number
  paragraphs: number
  words_added: number
  words_removed: number
  comments: number
  replies: number
  first_at: string | null
  last_at: string | null
}
export type ReviewData = {
  document_id: string
  version_id: string
  version_number: number
  is_current: boolean
  can_review: boolean
  word: boolean
  total: number
  changes: ReviewChange[]
  people: ReviewPerson[]
  outside_body: Record<string, number>
  properties: Record<string, string | null>
}
export type Contributor = {
  name: string
  member_id: string | null
  external: boolean
  word: { insertions: number; deletions: number; formats: number; moves: number; words_added: number; words_removed: number; comments: number; replies: number }
  precentis: Record<string, number>
  versions: number[]
  first_at: string | null
  last_at: string | null
}

export const getReview = (id: string) => apiFetch<ReviewData>(`${base(id)}/review`)
export const getContributors = (id: string) => apiFetch<{ people: Contributor[] }>(`${base(id)}/contributors`).then((r) => r.people)
export const applyReview = (
  id: string,
  body: { base_version_id: string; action: 'accept' | 'reject'; keys?: string[]; authors?: string[]; all?: boolean; note?: string },
) => apiFetch<{ version_id: string; version_number: number; changes: number; by_author: Record<string, number>; note: string }>(
  `${base(id)}/review`, withLock(id, json('POST', body)))
export const downloadWithCommentsUrl = (id: string) => `${base(id)}/download-with-comments`
