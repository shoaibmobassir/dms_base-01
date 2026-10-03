import { apiFetch, authHeaders } from '@/api/client'

/** One file in an upload batch, as the server reports it. */
export type BatchFile = {
  relative_path?: string
  status: string
  document_id: string | null
  error?: string | null
}

export type UploadOutcome = { file: File; status: 'indexed' | 'duplicate' | 'failed'; documentId: string | null; error?: string }

/** Accepted file types (the server also checks the file's signature). */
export const ACCEPTED_TYPES = '.pdf,.docx,.txt'
export const MAX_FILE_MB = 50

const WAITING = new Set(['pending', 'queued', 'processing', 'running'])

async function readError(res: Response): Promise<string> {
  const text = await res.text()
  try {
    const detail = (JSON.parse(text) as { detail?: unknown }).detail
    if (typeof detail === 'string') return detail
  } catch {
    // not JSON
  }
  return text || `Upload failed (HTTP ${res.status})`
}

/** The name a file is filed under: its folder path when it came from a folder, else its name. */
export const pathOf = (f: File): string => (f as File & { webkitRelativePath?: string }).webkitRelativePath || f.name

/** Why a file cannot be uploaded, or null when it can. */
export function fileProblem(file: File): string | null {
  const ext = file.name.split('.').pop()?.toLowerCase() ?? ''
  if (!['pdf', 'docx', 'txt'].includes(ext)) return 'Only PDF, Word (.docx) and text files are supported.'
  if (file.size === 0) return 'The file is empty.'
  if (file.size > MAX_FILE_MB * 1024 * 1024) return `Larger than ${MAX_FILE_MB} MB.`
  return null
}

/**
 * Files documents into one matter: create the batch, run it, and wait until every file is
 * indexed, skipped as a duplicate or failed. `onProgress` is called with the files' live status.
 */
export async function uploadToMatter(
  matterId: string,
  files: File[],
  opts: { signal?: AbortSignal; onProgress?: (done: number, total: number) => void } = {},
): Promise<UploadOutcome[]> {
  const body = new FormData()
  body.append('matter_id', matterId)
  for (const f of files) {
    body.append('files', f)
    body.append('relative_paths', pathOf(f))
  }
  const created = await fetch('/api/uploads/batches', { method: 'POST', headers: authHeaders(), body, signal: opts.signal, credentials: 'same-origin' })
  if (!created.ok) throw new Error(await readError(created))
  const batch = (await created.json()) as { batch_id: string; files?: BatchFile[] }

  const ran = await fetch(`/api/uploads/batches/${encodeURIComponent(batch.batch_id)}/run`, {
    method: 'POST',
    headers: authHeaders(),
    signal: opts.signal,
    credentials: 'same-origin',
  })
  if (!ran.ok && ran.status !== 202) throw new Error(await readError(ran))

  let rows: BatchFile[] = ran.status === 202 ? [] : (((await ran.json()) as { batch?: { files?: BatchFile[] }; files?: BatchFile[] }).batch?.files ?? [])
  // Queue mode (and some responses) return no files: poll until the worker is done.
  for (let i = 0; i < 150 && (rows.length === 0 || rows.some((f) => WAITING.has(f.status))); i++) {
    if (opts.signal?.aborted) throw new DOMException('Upload cancelled', 'AbortError')
    await new Promise((r) => setTimeout(r, 2000))
    const polled = await apiFetch<{ batch: { files: BatchFile[] } }>(`/api/uploads/batches/${encodeURIComponent(batch.batch_id)}`, { signal: opts.signal })
    rows = polled.batch.files
    opts.onProgress?.(rows.filter((f) => !WAITING.has(f.status)).length, files.length)
  }
  opts.onProgress?.(files.length, files.length)

  return files.map((file, i) => {
    const row = rows.find((r) => r.relative_path === pathOf(file)) ?? rows[i]
    if (!row) return { file, status: 'failed', documentId: null, error: 'No result was reported for this file.' }
    if (row.status === 'indexed') return { file, status: 'indexed', documentId: row.document_id }
    if (row.status === 'skipped') return { file, status: 'duplicate', documentId: row.document_id }
    return { file, status: 'failed', documentId: row.document_id, error: row.error || 'The file could not be indexed.' }
  })
}
