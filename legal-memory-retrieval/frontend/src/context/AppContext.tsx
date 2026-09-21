import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { apiFetch, setMemberId } from '../api/client'
import type {
  ClientItem,
  DocumentItem,
  HomeStats,
  Matter,
  PersonItem,
  ProjectItem,
} from '../api/types'
import { PERSONAS } from '../api/types'

type FirmData = {
  stats: HomeStats | null
  matters: Matter[]
  documents: DocumentItem[]
  clients: ClientItem[]
  people: PersonItem[]
  projects: ProjectItem[]
}

type AppContextValue = FirmData & {
  persona: string
  setPersona: (id: string) => void
  loading: boolean
  error: string | null
  refresh: () => Promise<void>
  toast: (msg: string) => void
  toasts: string[]
}

const AppContext = createContext<AppContextValue | null>(null)

const empty: FirmData = {
  stats: null,
  matters: [],
  documents: [],
  clients: [],
  people: [],
  projects: [],
}

export function AppProvider({ children }: { children: ReactNode }) {
  const [persona, setPersonaState] = useState<string>(PERSONAS[0].id)
  const [data, setData] = useState<FirmData>(empty)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [toasts, setToasts] = useState<string[]>([])

  const toast = useCallback((msg: string) => {
    setToasts((prev) => [...prev, msg])
    window.setTimeout(() => {
      setToasts((prev) => prev.slice(1))
    }, 2800)
  }, [])

  const refresh = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const [stats, matters, documents, clients, people, projects] =
        await Promise.all([
          apiFetch<HomeStats>('/api/home/stats').catch(() => null),
          apiFetch<{ items: Matter[] }>('/api/matters?limit=200'),
          apiFetch<{ items: DocumentItem[] }>('/api/documents?limit=200'),
          apiFetch<{ items: ClientItem[] }>('/api/clients?limit=200').catch(
            () => ({ items: [] }),
          ),
          apiFetch<{ items?: PersonItem[] } | PersonItem[]>('/api/people').catch(
            () => ({ items: [] }),
          ),
          apiFetch<{ items: ProjectItem[] }>('/api/projects?limit=200').catch(
            () => ({ items: [] }),
          ),
        ])

      const peopleItems = Array.isArray(people)
        ? people
        : people.items || []

      setData({
        stats,
        matters: matters.items || [],
        documents: documents.items || [],
        clients: clients.items || [],
        people: peopleItems,
        projects: projects.items || [],
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load firm data')
    } finally {
      setLoading(false)
    }
  }, [])

  const setPersona = useCallback((id: string) => {
    setMemberId(id)
    setPersonaState(id)
  }, [])

  useEffect(() => {
    setMemberId(persona)
    void refresh()
  }, [persona, refresh])

  const value = useMemo(
    () => ({
      ...data,
      persona,
      setPersona,
      loading,
      error,
      refresh,
      toast,
      toasts,
    }),
    [data, persona, setPersona, loading, error, refresh, toast, toasts],
  )

  return <AppContext.Provider value={value}>{children}</AppContext.Provider>
}

export function useApp() {
  const ctx = useContext(AppContext)
  if (!ctx) throw new Error('useApp must be used within AppProvider')
  return ctx
}
