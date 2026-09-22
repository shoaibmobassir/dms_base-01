export type Matter = {
  matter_id: string
  matter_code?: string
  title: string
  client_id?: string
  client_name?: string
  practice_area?: string
  matter_type?: string
  status?: string
  jurisdiction?: string
  opened_date?: string | null
  closed_date?: string | null
  restricted?: boolean
}

export type DocumentItem = {
  document_id: string
  matter_id?: string
  matter_code?: string
  title: string
  document_type?: string
  author_name?: string
  doc_date?: string | null
  status?: string
  version?: number | string
}

export type ClientItem = {
  client_id: string
  name: string
  industry?: string
  status?: string
}

export type PersonItem = {
  member_id: string
  name: string
  role?: string
  office?: string
  practice_area?: string
}

export type ProjectItem = {
  project_id: string
  title: string
  matter_id?: string
  status?: string
  team?: string
  lead_lawyer?: string
}

export type HomeStats = {
  service?: string
  firm?: string
  counts?: {
    matters?: number
    documents?: number
    clients?: number
    people?: number
    projects?: number
    [key: string]: unknown
  }
  matters?: number
  documents?: number
  clients?: number
  people?: number
  projects?: number
  [key: string]: unknown
}

export type ChatSession = {
  id: string
  title?: string | null
  matter_id?: string | null
  model?: string | null
  member_id?: string | null
  status?: string
  created_at?: string
  updated_at?: string
}

export type ChatMessage = {
  id?: string
  session_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  events?: Array<Record<string, unknown>>
  citations?: Array<Record<string, unknown>>
  created_at?: string
}

export type AskResult = {
  answer?: string
  key_finding?: string
  abstained?: boolean
  reason?: string
  hits?: Array<Record<string, unknown>>
  structured_citations?: Array<Record<string, unknown>>
  sources?: Array<Record<string, unknown>>
  latency_ms?: Record<string, number>
  provider?: string
  [key: string]: unknown
}

export const PERSONAS = [
  { id: 'MEM-00001', label: 'Aryan Maharaj (Lead Partner — Mumbai)' },
  { id: 'MEM-00002', label: 'Udant Dewan (Partner — Delhi)' },
  { id: 'MEM-00049', label: 'Alka Wable (Associate — Bengaluru)' },
  { id: 'RESTRICTED_DEMO', label: 'Outside Counsel (Ethical Wall Demo)' },
] as const
