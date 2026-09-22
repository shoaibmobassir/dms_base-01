import { apiFetch } from './client'
import type { ProjectItem } from './types'

export type Milestone = {
  title: string
  done?: boolean
  due?: string | null
}

export type ProjectFolder = {
  folder_id: string
  project_id?: string
  name: string
  parent_folder_id?: string | null
  document_count?: number
  children?: ProjectFolder[]
}

export type ProjectDetail = Omit<ProjectItem, 'team'> & {
  matter_code?: string
  matter_title?: string
  client_id?: string
  client_name?: string
  practice_team?: string
  team?: Array<Record<string, unknown>> | string
  progress?: number
  deadline?: string | null
  scope?: string
  milestones?: Milestone[]
  documents?: Array<Record<string, unknown>>
  folders?: ProjectFolder[]
  recent_activity?: Array<Record<string, unknown>>
  document_count?: number
}

export type CreateProjectBody = {
  title: string
  matter_id: string
  practice_team: string
  lead_lawyer?: string
  lead_member_id?: string
  deadline?: string
  scope?: string
  milestones?: Milestone[]
}

export function listProjects(limit = 200) {
  return apiFetch<{ items: ProjectItem[]; total?: number }>(
    `/api/projects?limit=${limit}`,
  )
}

export function getProject(projectId: string) {
  return apiFetch<ProjectDetail>(
    `/api/projects/${encodeURIComponent(projectId)}`,
  )
}

export function createProject(body: CreateProjectBody) {
  return apiFetch<ProjectDetail>('/api/projects', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function getProjectDirectory(projectId: string) {
  return apiFetch<{
    folders?: ProjectFolder[]
    folder_tree?: ProjectFolder[]
    tree?: ProjectFolder[]
    root_document_count?: number
  }>(`/api/projects/${encodeURIComponent(projectId)}/directory`)
}

export function getProjectDocuments(projectId: string, limit = 200) {
  return apiFetch<{ items?: Array<Record<string, unknown>>; documents?: Array<Record<string, unknown>> }>(
    `/api/projects/${encodeURIComponent(projectId)}/documents?limit=${limit}`,
  )
}

export function getProjectActivity(projectId: string, limit = 50) {
  return apiFetch<{ items?: Array<Record<string, unknown>> }>(
    `/api/projects/${encodeURIComponent(projectId)}/activity?limit=${limit}`,
  )
}

export function createFolder(
  projectId: string,
  name: string,
  parentFolderId?: string | null,
) {
  return apiFetch(`/api/projects/${encodeURIComponent(projectId)}/folders`, {
    method: 'POST',
    body: JSON.stringify({
      name,
      parent_folder_id: parentFolderId || null,
    }),
  })
}

export function deleteFolder(projectId: string, folderId: string) {
  return apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/folders/${encodeURIComponent(folderId)}`,
    { method: 'DELETE' },
  )
}

export function assignDocument(projectId: string, documentId: string) {
  return apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}`,
    { method: 'POST' },
  )
}

export function moveDocumentFolder(
  projectId: string,
  documentId: string,
  folderId: string | null,
) {
  return apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/documents/${encodeURIComponent(documentId)}/folder`,
    {
      method: 'PATCH',
      body: JSON.stringify({ folder_id: folderId }),
    },
  )
}

export function toggleMilestone(projectId: string, index: number, done: boolean) {
  return apiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/milestones/${index}`,
    {
      method: 'PATCH',
      body: JSON.stringify({ done }),
    },
  )
}

export function exportProject(projectId: string) {
  return apiFetch<{ export?: unknown }>(
    `/api/projects/${encodeURIComponent(projectId)}/export`,
  )
}
