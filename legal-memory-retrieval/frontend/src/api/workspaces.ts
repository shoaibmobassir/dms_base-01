import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { useApp } from '@/context/AppContext'
import { apiFetch, qs } from './client'

// Mirrors app/workspaces (plan 22, W0): matters, projects and personal libraries over single-copy documents.

const enc = encodeURIComponent
const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export type WorkspaceKind = 'matter' | 'project' | 'library' | 'firm'
export type Level = 'read' | 'edit' | 'manage'

export type ProjectSummary = {
  project_id: string
  title: string
  description: string | null
  owner_member_id: string | null
  owner_name: string | null
  created_at: string
  updated_at: string
  archived_at: string | null
  row_version: number
  document_count: number
  member_count: number
  my_role: 'owner' | 'editor' | 'viewer' | null
  matter: { matter_id: string; matter_code: string; title: string } | null
}

export type ProjectMember = {
  principal_type: 'member' | 'team'
  principal_id: string
  role: 'owner' | 'editor' | 'viewer'
  name: string | null
  title: string | null
  team_size: number | null
}

export type ProjectDetail = Omit<ProjectSummary, 'document_count' | 'member_count'> & {
  my_level: Level
  members: ProjectMember[]
}

export type Tag = { key: string; label: string; kind: 'matter' | 'project' | 'library' | 'client' | 'type'; id?: string; home?: boolean }
export type DocTags = { system: Tag[]; user: string[] }

export type WorkspaceDocument = {
  document_id: string
  title: string
  document_type: string | null
  mime_type: string | null
  doc_date: string | null
  updated_at: string | null
  author_name: string | null
  home_kind: WorkspaceKind
  home_id: string | null
  matter_id: string | null
  private: boolean
  version_number: number | null
  folder: string
  placement: 'home' | 'link'
  link_id: number | null
  placed_at: string | null
  tags: DocTags
  restricted?: undefined
}
export type RestrictedPlacement = { restricted: true; link_id: number; folder: string; placement: 'link'; placed_at: string }
export type WorkspaceItem = WorkspaceDocument | RestrictedPlacement

export type WorkspaceFolder = { path: string; name: string; document_count: number }

export type WorkspaceListing = {
  kind: WorkspaceKind
  id: string
  label: string
  my_level: Level
  folder: string
  folders: WorkspaceFolder[]
  documents: WorkspaceItem[]
  total: number
}

export type Place = {
  kind: WorkspaceKind
  id?: string
  label?: string
  folder?: string
  home: boolean
  hidden?: boolean
  link_id?: number
  added_via?: string
}
export type DocumentPlaces = {
  document_id: string
  my_level: Level
  places: Place[]
  derived_from: { document_id: string; version_id: string | null; title: string | null } | null
  tags: DocTags
}

export type WorkspaceHit = {
  document_id: string
  title: string
  document_type: string | null
  folder_path: string | null
  chunk_id: string | null
  page_number: number | null
  match_kind: 'title' | 'content'
  snippet: string | null
}

export type DuplicateMatch = {
  document_id: string
  title: string
  already_here: boolean
  home: { kind: WorkspaceKind; id: string; label: string }
}

/** The library of the signed-in person is addressed as ``library/me``. */
export const containerPath = (kind: WorkspaceKind, id: string) => `${kind}/${enc(id)}`
export const workspaceHref = (kind: WorkspaceKind, id: string) => `/work/${kind}/${enc(id)}`

function useScoped<T>(key: unknown[], fn: () => Promise<T>, enabled = true) {
  const { identityKey } = useApp()
  return useQuery({
    queryKey: [identityKey, ...key],
    queryFn: fn,
    enabled: enabled && identityKey !== null,
    placeholderData: keepPreviousData,
  })
}

// ── projects ─────────────────────────────────────────────────────────────────

export type ProjectScope = 'all' | 'mine' | 'shared'
export const useProjectList = (p: { q?: string; archived?: boolean; scope?: ProjectScope; sort?: 'updated' | 'title'; matterId?: string; page?: number; enabled?: boolean } = {}) =>
  useScoped(['projects', p.q ?? '', !!p.archived, p.scope ?? 'all', p.sort ?? 'updated', p.matterId ?? '', p.page ?? 0], () =>
    apiFetch<{ items: ProjectSummary[]; total: number }>(`/api/projects${qs({
      q: p.q, archived: p.archived ? 'true' : undefined, scope: p.scope && p.scope !== 'all' ? p.scope : undefined,
      sort: p.sort && p.sort !== 'updated' ? p.sort : undefined, matter_id: p.matterId, limit: 50, offset: p.page ? p.page * 50 : undefined,
    })}`), p.enabled !== false)

export const useProjects = (p: { q?: string; archived?: boolean } = {}) =>
  useScoped(['projects', p.q ?? '', !!p.archived], () =>
    apiFetch<{ items: ProjectSummary[] }>(`/api/projects${qs({ q: p.q, archived: p.archived ? 'true' : undefined, limit: 200 })}`).then((r) => r.items),
  )

export const useProject = (id: string, enabled = true) =>
  useScoped(['project', id], () => apiFetch<ProjectDetail>(`/api/projects/${enc(id)}`), enabled && !!id)

export const createProject = (body: { title: string; description?: string; matter_id?: string | null }) =>
  apiFetch<ProjectDetail>('/api/projects', json('POST', body))
export const updateProject = (id: string, body: { title?: string; description?: string | null; matter_id?: string | null; row_version?: number }) =>
  apiFetch<ProjectDetail>(`/api/projects/${enc(id)}`, json('PATCH', body))
export const archiveProject = (id: string, archived: boolean) =>
  apiFetch<ProjectDetail>(`/api/projects/${enc(id)}/${archived ? 'archive' : 'restore'}`, json('POST'))
export const setProjectMember = (id: string, body: { principal_type: 'member' | 'team'; principal_id: string; role: ProjectMember['role'] }) =>
  apiFetch<{ members: ProjectMember[] }>(`/api/projects/${enc(id)}/members`, json('PUT', body))
export const removeProjectMember = (id: string, type: 'member' | 'team', principalId: string) =>
  apiFetch<{ members: ProjectMember[] }>(`/api/projects/${enc(id)}/members/${type}/${enc(principalId)}`, json('DELETE'))

// ── workspace contents ───────────────────────────────────────────────────────

export const useWorkspaceItems = (
  kind: WorkspaceKind,
  id: string,
  p: { folder?: string; recursive?: boolean; q?: string; tag?: string; enabled?: boolean; offset?: number; limit?: number } = {},
) =>
  useScoped(['workspace', kind, id, 'items', p.folder ?? '', !!p.recursive, p.q ?? '', p.tag ?? '', p.offset ?? 0, p.limit ?? 1000], () =>
    apiFetch<WorkspaceListing>(
      `/api/workspaces/${containerPath(kind, id)}/items${qs({ folder: p.folder, recursive: p.recursive ? 'true' : undefined, q: p.q, tag: p.tag, limit: p.limit ?? 1000, offset: p.offset || undefined })}`,
    ),
    p.enabled !== false && !!id,
  )

export const useWorkspaceSearch = (kind: WorkspaceKind, id: string, q: string) =>
  useScoped(['workspace', kind, id, 'search', q], () =>
    apiFetch<{ query: string; results: WorkspaceHit[] }>(`/api/workspaces/${containerPath(kind, id)}/search${qs({ q })}`).then((r) => r.results),
    !!id && q.trim().length >= 2,
  )

export const useDocumentPlaces = (documentId: string, enabled = true) =>
  useScoped(['document-places', documentId], () => apiFetch<DocumentPlaces>(`/api/workspaces/documents/${enc(documentId)}`), enabled && !!documentId)

export const createFolder = (kind: WorkspaceKind, id: string, path: string) =>
  apiFetch(`/api/workspaces/${containerPath(kind, id)}/folders`, json('POST', { path }))
export const renameFolder = (kind: WorkspaceKind, id: string, path: string, newPath: string) =>
  apiFetch(`/api/workspaces/${containerPath(kind, id)}/folders`, json('PATCH', { path, new_path: newPath }))
export const deleteFolder = (kind: WorkspaceKind, id: string, path: string) =>
  apiFetch(`/api/workspaces/${containerPath(kind, id)}/folders${qs({ path })}`, json('DELETE'))

type Target = { kind: WorkspaceKind; id: string; folder?: string }
export const linkDocument = (documentId: string, t: Target) =>
  apiFetch(`/api/workspaces/documents/${enc(documentId)}/links`, json('POST', t))
export const unlinkDocument = (documentId: string, kind: WorkspaceKind, id: string) =>
  apiFetch(`/api/workspaces/documents/${enc(documentId)}/links/${containerPath(kind, id)}`, json('DELETE'))
export const moveHome = (documentId: string, t: Target) =>
  apiFetch<DocumentPlaces>(`/api/workspaces/documents/${enc(documentId)}/move-home`, json('POST', t))
export const copyDocument = (documentId: string, t: Target & { title?: string }) =>
  apiFetch<{ document_id: string; title: string }>(`/api/workspaces/documents/${enc(documentId)}/copy`, json('POST', t))
export const placeInFolder = (documentId: string, t: Target) =>
  apiFetch(`/api/workspaces/documents/${enc(documentId)}/folder`, json('PATCH', t))
export const addTag = (documentId: string, tag: string) =>
  apiFetch<DocTags>(`/api/workspaces/documents/${enc(documentId)}/tags`, json('POST', { tag }))
export const removeTag = (documentId: string, tag: string) =>
  apiFetch<DocTags>(`/api/workspaces/documents/${enc(documentId)}/tags/${enc(tag)}`, json('DELETE'))
export const checkDuplicates = (kind: WorkspaceKind, id: string, hashes: string[]) =>
  apiFetch<{ matches: Record<string, DuplicateMatch[]> }>('/api/workspaces/duplicates', json('POST', { kind, id, hashes }))

export const getWorkbenchState = (kind: WorkspaceKind, id: string) =>
  apiFetch<{ state: Record<string, unknown> }>(`/api/workspaces/${containerPath(kind, id)}/state`)
export const putWorkbenchState = (kind: WorkspaceKind, id: string, state: unknown) =>
  apiFetch(`/api/workspaces/${containerPath(kind, id)}/state`, json('PUT', { state }))

/** SHA-256 of a file in the browser, to ask the server for an existing copy before uploading. */
export async function sha256Hex(file: Blob): Promise<string> {
  const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
  return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, '0')).join('')
}

/** Delete an empty project (owners). The server refuses while anything is still in it. */
export const deleteProject = (id: string) => apiFetch<{ deleted: boolean }>(`/api/projects/${enc(id)}`, json('DELETE'))

export const renameDocument = (documentId: string, title: string) =>
  apiFetch<{ document_id: string; title: string }>(`/api/workspaces/documents/${enc(documentId)}`, json('PATCH', { title }))

export type LibraryShare = { principal_type: 'member' | 'team'; principal_id: string; level: 'read' | 'edit'; name: string | null }
export const useLibraryShares = (documentId: string, enabled = true) =>
  useScoped(['library-shares', documentId], () =>
    apiFetch<{ shares: LibraryShare[] }>(`/api/workspaces/documents/${enc(documentId)}/shares`).then((r) => r.shares), enabled && !!documentId)
export const shareLibraryDocument = (documentId: string, body: { principal_type: 'member' | 'team'; principal_id: string; level: 'read' | 'edit' | null }) =>
  apiFetch<{ shares: LibraryShare[] }>(`/api/workspaces/documents/${enc(documentId)}/shares`, json('PUT', body))

/** Documents other people shared with me from their libraries. */
export const useSharedWithMe = (enabled = true) =>
  useScoped(['workspace', 'shared-with-me'], () =>
    apiFetch<{ documents: (WorkspaceDocument & { owner_name: string | null; share_level: 'read' | 'edit' })[] }>('/api/workspaces/shared-with-me').then((r) => r.documents), enabled)

/** Tags people have used on documents they can read, most used first (for filters and autocomplete). */
export const useTagSuggestions = (prefix = '', enabled = true) =>
  useScoped(['workspace', 'tags', prefix], () =>
    apiFetch<{ tags: { tag: string; n?: number; count?: number }[] }>(`/api/workspaces/tags${qs({ prefix })}`).then((r) => r.tags), enabled)

/** The title shown to people: without the file extension the upload left on it. */
export const displayTitle = (title: string | null | undefined) => (title ?? '').replace(/\.(pdf|docx?|txt|md|xlsx?|rtf)$/i, '')
