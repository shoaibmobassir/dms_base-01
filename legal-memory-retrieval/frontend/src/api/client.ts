// Caller identity. With AUTH_ENABLED=true the API needs X-Api-Key; in local dev
// (auth off) it trusts X-Member-Id so the persona switcher can demo the ethical wall.
type Identity = { apiKey: string | null; memberId: string | null }

const identity: Identity = { apiKey: null, memberId: null }

export function setIdentity(next: Partial<Identity>) {
  Object.assign(identity, next)
}

function cookie(name: string): string | null {
  const match = document.cookie.split('; ').find((c) => c.startsWith(`${name}=`))
  return match ? decodeURIComponent(match.slice(name.length + 1)) : null
}

/**
 * Identity headers for a request. With firm sign-in the session travels in an
 * HttpOnly cookie the browser sends itself; we only echo the CSRF token.
 */
export function authHeaders(): Record<string, string> {
  const headers: Record<string, string> = {}
  const csrf = cookie('precentis_csrf')
  if (csrf) headers['X-CSRF-Token'] = csrf
  if (identity.apiKey) headers['X-Api-Key'] = identity.apiKey
  else if (identity.memberId) headers['X-Member-Id'] = identity.memberId
  return headers
}

/** Fired when the API says the caller is no longer signed in (session expired or revoked). */
export const UNAUTHORIZED_EVENT = 'precentis:unauthorized'

export class ApiError extends Error {
  status: number
  body: string

  constructor(status: number, body: string) {
    super(ApiError.describe(status, body))
    this.status = status
    this.body = body
  }

  static describe(status: number, body: string) {
    try {
      const detail = (JSON.parse(body) as { detail?: unknown }).detail
      if (typeof detail === 'string') return `${detail} (HTTP ${status})`
    } catch {
      // not JSON
    }
    return `Request failed (HTTP ${status})`
  }
}

export async function apiFetch<T = unknown>(path: string, options: RequestInit = {}): Promise<T> {
  const headers = new Headers(options.headers || {})
  if (!headers.has('Content-Type') && options.body) {
    headers.set('Content-Type', 'application/json')
  }
  for (const [k, v] of Object.entries(authHeaders())) headers.set(k, v)

  const res = await fetch(path, { ...options, headers, credentials: 'same-origin' })
  if (!res.ok) {
    if (res.status === 401) window.dispatchEvent(new Event(UNAUTHORIZED_EVENT))
    throw new ApiError(res.status, await res.text())
  }
  if (res.status === 204) return undefined as T
  const text = await res.text()
  if (!text) return undefined as T
  return JSON.parse(text) as T
}

export function qs(params: Record<string, string | number | undefined | null>) {
  const search = new URLSearchParams()
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') search.set(k, String(v))
  }
  const s = search.toString()
  return s ? `?${s}` : ''
}
