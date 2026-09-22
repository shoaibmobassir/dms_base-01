import { apiFetch } from './client'

export type DocVersion = {
  version_id: string
  version_number?: number
  version_label?: string
  version_status?: string
  title?: string
  author_name?: string
  created_at?: string
  source?: string
  content_sha256?: string
  body?: string
}

export function listVersions(documentId: string) {
  return apiFetch<{ versions?: DocVersion[] }>(
    `/api/documents/${encodeURIComponent(documentId)}/versions`,
  )
}

export function getVersion(documentId: string, versionId: string) {
  return apiFetch<{ version?: DocVersion }>(
    `/api/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}`,
  )
}

export function compareVersions(
  documentId: string,
  versionId: string,
  compareWith: string,
) {
  return apiFetch<{
    diff?: string
    version_a?: DocVersion
    version_b?: DocVersion
  }>(
    `/api/documents/${encodeURIComponent(documentId)}/versions/${encodeURIComponent(versionId)}/diff?compare_with=${encodeURIComponent(compareWith)}`,
  )
}

export function createDevelopingVersion(
  documentId: string,
  authorName?: string,
) {
  return apiFetch<{ version?: DocVersion }>(
    `/api/documents/${encodeURIComponent(documentId)}/versions/developing`,
    {
      method: 'POST',
      body: JSON.stringify({ author_name: authorName || 'Counsel' }),
    },
  )
}

export function getDocumentText(documentId: string, opts?: { q?: string; chunk_id?: string }) {
  const params = new URLSearchParams()
  if (opts?.q) params.set('q', opts.q)
  if (opts?.chunk_id) params.set('chunk_id', opts.chunk_id)
  const qs = params.toString()
  return apiFetch<{ text?: string; body?: string; highlight?: string }>(
    `/api/documents/${encodeURIComponent(documentId)}/text${qs ? `?${qs}` : ''}`,
  )
}

export function getDocumentDetail(
  documentId: string,
  opts?: { q?: string; chunk_id?: string },
) {
  const params = new URLSearchParams()
  if (opts?.q) params.set('q', opts.q)
  if (opts?.chunk_id) params.set('chunk_id', opts.chunk_id)
  const qs = params.toString()
  return apiFetch<Record<string, unknown>>(
    `/api/documents/${encodeURIComponent(documentId)}${qs ? `?${qs}` : ''}`,
  )
}

export type IngestBody = {
  title: string
  matter_id: string
  document_type?: string
  author_name?: string
  body: string
  version?: string
  status?: string
}

export function ingestDocument(body: IngestBody) {
  return apiFetch<{
    document_id?: string
    status?: string
    chunks_indexed?: number
  }>('/api/documents/ingest', {
    method: 'POST',
    body: JSON.stringify({
      document_type: 'Contract Draft',
      version: 'v1.0',
      status: 'Indexed',
      ...body,
    }),
  })
}
