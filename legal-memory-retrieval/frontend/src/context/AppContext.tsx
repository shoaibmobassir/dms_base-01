import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { toast as sonnerToast } from 'sonner'
import { ApiError, apiFetch, setIdentity, UNAUTHORIZED_EVENT } from '@/api/client'
import type { FirmProfile, Person } from '@/api/types'

const PERSONA_KEY = 'precentis.persona'
const API_KEY = 'precentis.apiKey'

function readStore(store: 'local' | 'session', key: string): string | null {
  try {
    return (store === 'local' ? localStorage : sessionStorage).getItem(key)
  } catch {
    return null
  }
}

function writeStore(store: 'local' | 'session', key: string, value: string | null) {
  try {
    const s = store === 'local' ? localStorage : sessionStorage
    if (value === null) s.removeItem(key)
    else s.setItem(key, value)
  } catch {
    // storage unavailable (private mode) — identity lasts for this tab only
  }
}

type BootState =
  | { phase: 'loading' }
  | { phase: 'error'; message: string }
  | { phase: 'needs-key'; error?: string }  // signed out: offer firm sign-in and/or a dev API key
  | { phase: 'ready' }

export type AuthOptions = { oidc: boolean; apiKey: boolean }

type AppContextValue = {
  boot: BootState
  /** Sign-in methods the server offers (when auth is on). */
  authOptions: AuthOptions
  firm: FirmProfile | null
  authEnabled: boolean
  /** The signed-in member (auth on) or the selected persona (dev). */
  me: Person | null
  /** Members offered in the dev persona switcher; empty when auth is on. */
  personas: Person[]
  /** Prefix for every query key; null until identity is known. */
  identityKey: string | null
  setPersona: (memberId: string) => void
  signIn: (apiKey: string) => Promise<void>
  signOut: () => void
  retryBoot: () => void
  toast: (msg: string) => void
}

const AppContext = createContext<AppContextValue | null>(null)

export function AppProvider({ children }: { children: ReactNode }) {
  const queryClient = useQueryClient()
  const [boot, setBoot] = useState<BootState>({ phase: 'loading' })
  const [firm, setFirm] = useState<FirmProfile | null>(null)
  const [authEnabled, setAuthEnabled] = useState(false)
  const [authOptions, setAuthOptions] = useState<AuthOptions>({ oidc: false, apiKey: false })
  const [personas, setPersonas] = useState<Person[]>([])
  const [me, setMe] = useState<Person | null>(null)
  const [identityKey, setIdentityKey] = useState<string | null>(null)
  const [attempt, setAttempt] = useState(0)

  const toast = useCallback((msg: string) => {
    sonnerToast(msg)
  }, [])

  const adoptIdentity = useCallback(async (key: string) => {
    const res = await apiFetch<{ person: Person }>('/api/people/me')
    setMe(res.person)
    setIdentityKey(key)
    setBoot({ phase: 'ready' })
  }, [])

  const signIn = useCallback(
    async (apiKey: string) => {
      setIdentity({ apiKey, memberId: null })
      try {
        await adoptIdentity(`key:${apiKey.slice(-6)}`)
        writeStore('session', API_KEY, apiKey)
      } catch (err) {
        setIdentity({ apiKey: null })
        writeStore('session', API_KEY, null)
        setBoot({
          phase: 'needs-key',
          error: err instanceof ApiError && err.status === 401 ? 'That key was not accepted.' : String(err),
        })
      }
    },
    [adoptIdentity],
  )

  useEffect(() => {
    let cancelled = false
    setBoot({ phase: 'loading' })
    void (async () => {
      try {
        const [config, firmProfile] = await Promise.all([
          apiFetch<{ auth_enabled: boolean; oidc_enabled: boolean; api_key_login: boolean }>('/api/auth/config'),
          apiFetch<FirmProfile>('/api/system/firm'),
        ])
        if (cancelled) return
        setFirm(firmProfile)
        setAuthEnabled(config.auth_enabled)
        setAuthOptions({ oidc: config.oidc_enabled, apiKey: config.api_key_login })

        if (config.auth_enabled) {
          // 1. An existing firm sign-in session (HttpOnly cookie).
          try {
            const session = await apiFetch<{ person: Person }>('/api/auth/session')
            if (cancelled) return
            setIdentity({ apiKey: null, memberId: null })
            setMe(session.person)
            setIdentityKey(`session:${session.person.member_id}`)
            setBoot({ phase: 'ready' })
            return
          } catch {
            // not signed in
          }
          // 2. Development only: a pasted API key.
          const saved = config.api_key_login ? readStore('session', API_KEY) : null
          if (saved) await signIn(saved)
          else {
            const failed = new URLSearchParams(window.location.search).get('signin') === 'failed'
            setBoot({ phase: 'needs-key', error: failed ? 'Sign-in did not complete. Try again or contact your administrator.' : undefined })
          }
          return
        }

        const people = (await apiFetch<{ items: Person[] }>('/api/people')).items
        if (cancelled) return
        setPersonas(people)
        const saved = readStore('local', PERSONA_KEY)
        const persona = people.find((p) => p.member_id === saved) ?? people[0]
        if (!persona) {
          setBoot({ phase: 'error', message: 'No members exist yet. Run scripts/ingest.py and scripts/seed_demo.py.' })
          return
        }
        setIdentity({ memberId: persona.member_id, apiKey: null })
        await adoptIdentity(`member:${persona.member_id}`)
      } catch (err) {
        if (!cancelled) setBoot({ phase: 'error', message: err instanceof Error ? err.message : String(err) })
      }
    })()
    return () => {
      cancelled = true
    }
  }, [attempt, adoptIdentity, signIn])

  const setPersona = useCallback(
    (memberId: string) => {
      const persona = personas.find((p) => p.member_id === memberId)
      if (!persona) return
      writeStore('local', PERSONA_KEY, memberId)
      setIdentity({ memberId })
      setMe(persona)
      setIdentityKey(`member:${memberId}`)
    },
    [personas],
  )

  const endSession = useCallback(
    (message?: string) => {
      setIdentity({ apiKey: null, memberId: null })
      writeStore('session', API_KEY, null)
      queryClient.clear()
      setMe(null)
      setIdentityKey(null)
      setBoot({ phase: 'needs-key', error: message })
    },
    [queryClient],
  )

  const signOut = useCallback(() => {
    // Revoke the server session (no-op for API-key mode), then forget local state.
    void apiFetch('/api/auth/logout', { method: 'POST' })
      .catch(() => undefined)
      .finally(() => endSession())
  }, [endSession])

  // A 401 after sign-in means the session expired or was revoked by an administrator.
  useEffect(() => {
    if (!authEnabled || boot.phase !== 'ready') return
    const onUnauthorized = () => endSession('Your session has ended. Sign in again.')
    window.addEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
    return () => window.removeEventListener(UNAUTHORIZED_EVENT, onUnauthorized)
  }, [authEnabled, boot.phase, endSession])

  const retryBoot = useCallback(() => setAttempt((n) => n + 1), [])

  const value = useMemo(
    () => ({
      boot,
      authOptions,
      firm,
      authEnabled,
      me,
      personas,
      identityKey,
      setPersona,
      signIn,
      signOut,
      retryBoot,
      toast,
    }),
    [boot, authOptions, firm, authEnabled, me, personas, identityKey, setPersona, signIn, signOut, retryBoot, toast],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}

export function initials(name: string) {
  return name
    .split(/\s+/)
    .filter(Boolean)
    .slice(0, 2)
    .map((p) => p[0])
    .join('')
    .toUpperCase()
}
