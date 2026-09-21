let memberId = 'MEM-00001'

export function setMemberId(id: string) {
  memberId = id
}

export function getMemberId() {
  return memberId
}

export class ApiError extends Error {
  status: number
  body: string

  constructor(status: number, body: string) {
    super(`HTTP ${status}`)
    this.status = status
    this.body = body
  }
}

export async function apiFetch<T = unknown>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  headers.set('X-Member-Id', memberId)

  const res = await fetch(path, { ...options, headers })
  if (!res.ok) {
    const body = await res.text()
    throw new ApiError(res.status, body)
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}
