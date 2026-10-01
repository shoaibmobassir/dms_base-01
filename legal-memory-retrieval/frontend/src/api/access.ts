import { useQuery } from '@tanstack/react-query'
import { useApp } from '@/context/AppContext'
import { apiFetch } from './client'

// ── Types (mirror app/access and /api/access, /api/admin) ────────────────────

export type AccessMode = 'open' | 'team' | 'restricted'
export type AccessLevel = 'read' | 'edit' | 'manage'

export type MyAccess = { member_id: string | null; roles: string[]; permissions: string[] }

export type MatterGrant = {
  grant_id: string
  principal_type: 'member' | 'team'
  principal_id: string
  principal_name: string | null
  team_size: number | null
  level: AccessLevel
  reason: string
  expires_at: string | null
  granted_by: string | null
  granted_at: string
}

export type MatterScreen = { member_id: string; name: string; reason: string; created_by: string | null; created_at: string }

export type AccessRequest = {
  request_id: string
  matter_id: string
  matter_code?: string
  matter_title?: string
  requester_id: string
  requester_name?: string
  level: 'read' | 'edit'
  reason: string
  status: 'pending' | 'approved' | 'denied' | 'cancelled'
  created_at: string
  decision_note?: string | null
}

export type MatterAccess = {
  matter_id: string
  mode: AccessMode
  hide_existence: boolean
  row_version: number
  updated_by: string | null
  updated_at: string
  grants: MatterGrant[]
  screens: MatterScreen[]
  team: { member_id: string; name: string; role: string; role_on_matter: string | null }[]
  compiled: { restricted: boolean; allowed: number; denied: number; compiled_at: string } | null
  pending_requests: AccessRequest[]
  history: { occurred_at: string; member_id: string | null; action: string; detail: Record<string, unknown> }[]
  can_manage_screens: boolean
}

export type MatterAccessStatus = {
  matter_id: string
  matter_code: string
  title: string
  level: 'none' | AccessLevel
  can_request: boolean
  pending_request_id: string | null
}

export type AdminUser = {
  member_id: string
  name: string
  role: string
  office: string | null
  email: string | null
  practice_areas: string[]
  roles: string[]
  teams: string[]
  matter_count: number
}

export type FirmRole = { role_key: string; name: string; description: string; permissions: string[]; member_count: number }

export type Team = {
  team_id: string
  name: string
  kind: 'practice' | 'office' | 'matter' | 'custom'
  description: string
  member_count: number
  members: { member_id: string; name: string; role: string; team_role: string }[]
}

export type WallRow = {
  matter_id: string
  matter_code: string
  title: string
  client_name: string
  mode: AccessMode
  hide_existence: boolean
  allowed: number
  screened: number
  pending_requests: number
  updated_by: string | null
  updated_at: string
}

const enc = encodeURIComponent

function useScoped<T>(key: unknown[], fn: () => Promise<T>, enabled = true) {
  const { identityKey } = useApp()
  return useQuery({ queryKey: [identityKey, ...key], queryFn: fn, enabled: enabled && identityKey !== null, retry: false })
}

// ── Queries ──────────────────────────────────────────────────────────────────

export const useMyAccess = () => useScoped(['access-me'], () => apiFetch<MyAccess>('/api/access/me'))

export const can = (me: MyAccess | undefined, permission: string) =>
  !!me && (me.permissions.includes('*') || me.permissions.includes(permission))

export const useMatterAccess = (matterId: string) =>
  useScoped(['matter-access', matterId], () => apiFetch<MatterAccess>(`/api/access/matters/${enc(matterId)}`), !!matterId)

export const useMatterAccessStatus = (matterId: string, enabled: boolean) =>
  useScoped(
    ['matter-access-status', matterId],
    () => apiFetch<MatterAccessStatus>(`/api/access/matters/${enc(matterId)}/status`),
    enabled && !!matterId,
  )

export const useAccessRequests = (scope: 'mine' | 'to_decide') =>
  useScoped(['access-requests', scope], () =>
    apiFetch<{ items: AccessRequest[] }>(`/api/access/requests?scope=${scope}`).then((r) => r.items),
  )

export const useAdminUsers = () => useScoped(['admin-users'], () => apiFetch<{ items: AdminUser[] }>('/api/admin/users').then((r) => r.items))
export const useFirmRoles = () => useScoped(['admin-roles'], () => apiFetch<{ items: FirmRole[] }>('/api/admin/roles').then((r) => r.items))
export const useTeams = () => useScoped(['admin-teams'], () => apiFetch<{ items: Team[] }>('/api/admin/teams').then((r) => r.items))
export const useWalls = () => useScoped(['admin-walls'], () => apiFetch<{ items: WallRow[] }>('/api/admin/walls').then((r) => r.items))

// ── Commands ─────────────────────────────────────────────────────────────────

const json = (method: string, body?: unknown): RequestInit => ({ method, body: body === undefined ? undefined : JSON.stringify(body) })

export const setMatterMode = (matterId: string, body: { mode: AccessMode; hide_existence?: boolean; row_version?: number }) =>
  apiFetch(`/api/access/matters/${enc(matterId)}`, json('PUT', body))

export const addGrant = (
  matterId: string,
  body: { principal_type: 'member' | 'team'; principal_id: string; level: AccessLevel; reason: string; expires_at?: string | null },
) => apiFetch<MatterGrant>(`/api/access/matters/${enc(matterId)}/grants`, json('POST', body))

export const removeGrant = (matterId: string, grantId: string) =>
  apiFetch(`/api/access/matters/${enc(matterId)}/grants/${enc(grantId)}`, json('DELETE'))

export const addScreen = (matterId: string, body: { member_id: string; reason: string }) =>
  apiFetch(`/api/access/matters/${enc(matterId)}/screens`, json('POST', body))

export const removeScreen = (matterId: string, memberId: string) =>
  apiFetch(`/api/access/matters/${enc(matterId)}/screens/${enc(memberId)}`, json('DELETE'))

export const requestAccess = (matterId: string, body: { level: 'read' | 'edit'; reason: string }) =>
  apiFetch<AccessRequest>(`/api/access/matters/${enc(matterId)}/requests`, json('POST', body))

export const decideRequest = (requestId: string, body: { approve: boolean; note?: string }) =>
  apiFetch(`/api/access/requests/${enc(requestId)}/decision`, json('POST', body))

export const setUserRoles = (memberId: string, roles: string[]) =>
  apiFetch(`/api/admin/users/${enc(memberId)}/roles`, json('PUT', { roles }))

export const createTeam = (body: { name: string; kind: Team['kind']; description?: string }) =>
  apiFetch<Team>('/api/admin/teams', json('POST', body))

export const deleteTeam = (teamId: string) => apiFetch(`/api/admin/teams/${enc(teamId)}`, json('DELETE'))

export const setTeamMember = (teamId: string, memberId: string, present: boolean) =>
  apiFetch(`/api/admin/teams/${enc(teamId)}/members/${enc(memberId)}`, json(present ? 'PUT' : 'DELETE', present ? { team_role: 'member' } : undefined))
