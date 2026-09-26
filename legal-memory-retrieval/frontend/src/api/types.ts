// Response types mirror the FastAPI payloads (see app/api/routers/*).
// Keep them in sync with tests/test_ui_contract.py.

export type Paged<T> = { total: number; items: T[] }

export type Matter = {
  matter_id: string
  matter_code: string
  title: string
  client_id: string
  client_name: string | null
  practice_area: string
  matter_type: string
  status: string | null
  jurisdiction: string | null
  opened_date: string | null
  closed_date: string | null
  outcome: string | null
  restricted: boolean
}

export type TeamMember = {
  member_id: string
  name: string
  role: string
  role_on_matter: string
  office: string | null
}

export type MatterDetail = {
  matter: Matter & {
    opposing_party: string | null
    court: string | null
    office: string | null
    legal_issues: string[]
    facts: string[]
    classification: string
  }
  team: TeamMember[]
  documents: DocumentItem[]
}

export type TimelineEvent = {
  date: string | null
  author: string | null
  event: string
  doc_id: string
  doc_type: string
}

export type MatterArgument = {
  argument_id: string
  issue: string
  position: string | null
  argument: string
  outcome: string | null
}

export type RelatedMatter = Pick<
  Matter,
  'matter_id' | 'matter_code' | 'title' | 'client_name' | 'practice_area' | 'status' | 'outcome' | 'restricted'
>

export type DocumentItem = {
  document_id: string
  matter_id?: string
  matter_code?: string
  title: string
  document_type: string
  author_name: string | null
  doc_date: string | null
  status: string | null
  version: string | null
}

export type DocumentDetail = DocumentItem & {
  client_id: string | null
  body: string | null
  highlighted_body: string | null
  match_count: number
  chunks: { chunk_id: string; chunk_index: number; text: string }[]
  highlight_chunk_id: string | null
  matter_info: { title: string; client_name: string | null; court: string | null; practice_area: string } | null
  current_version_id?: string | null
  chunk_count?: number
  block_count?: number
  page_count?: number | null
  has_original?: boolean
  current_version?: {
    version_id: string
    version_number?: number
    version_status?: string
    version_label?: string
    author_name?: string
    created_at?: string
    change_summary?: string
    page_count?: number | null
  }
}

export type DocVersion = {
  version_id: string
  version_number?: number
  version_label?: string
  version_status?: string
  author_name?: string
  created_at?: string
  body?: string
  change_summary?: string
  page_count?: number | null
  parent_version_id?: string | null
  content_sha256?: string
  source?: string
}

export type DocumentOutlineItem = {
  block_id: string
  section_id: string | null
  section_title: string
  page_number: number
  sequence: number | null
  index: number
  outline_source: 'native' | 'generated'
}

export type DocumentChunk = {
  chunk_id: string
  chunk_index: number
  text: string
}

export type DocumentBlock = {
  block_id: string
  page_number?: number
  sequence?: number
  section_id?: string | null
  section_title?: string | null
  block_type?: string
  text: string
  start_offset?: number
  end_offset?: number
}

export type ClientItem = {
  client_id: string
  name: string
  industry: string | null
  size: string | null
  headquarters: string | null
}

export type ClientNote = {
  note_id: string
  kind: 'prefers' | 'avoid' | 'terms'
  text: string
  source_matter_id: string | null
  source_matter_code: string | null
  author_name: string | null
}

export type ClientDetail = ClientItem & {
  locations: string[]
  aliases: string[]
  matters: Pick<Matter, 'matter_id' | 'matter_code' | 'title' | 'practice_area' | 'status' | 'opened_date'>[]
  notes: ClientNote[]
}

export type Person = {
  member_id: string
  name: string
  role: string
  practice_areas: string[]
  specializations: string[]
  office: string | null
  joined_year: number | null
  is_lawyer: boolean
}

export type PersonDetail = {
  person: Person
  matters: (Pick<Matter, 'matter_id' | 'matter_code' | 'title' | 'status' | 'practice_area'> & {
    role_on_matter: string
  })[]
}

export type Deadline = {
  id: string
  title: string
  kind: 'hearing' | 'filing' | 'limitation' | 'compliance'
  due: string
  status: 'open' | 'done'
  notes: string | null
  court: string | null
  matter_id: string
  matter_code: string
  matter_title: string
  client_name: string | null
  owner_member_id: string | null
  owner_name: string | null
}

export type ArgumentItem = MatterArgument & {
  matter_id: string
  matter_code: string
  matter_title: string
  practice_area: string
}

export type Team = { name: string; lawyers: number; active_matters: number }

export type HomeStats = {
  firm: string
  counts: {
    matters: number
    documents: number
    arguments: number
    clients: number
    open_deadlines: number
    people: number
  }
}

export type SearchResult = {
  kind: 'matter' | 'document' | 'client' | 'member'
  id: string
  code: string
  title: string
  subtitle: string | null
  meta: string | null
  status: string | null
}

export type FirmProfile = {
  name: string
  descriptor: string | null
  office: string | null
}

export type SystemInfo = {
  auth_enabled: boolean
  retrieval_engine: string
  index_version: string
  embedding_version: string
  knowledge_version: number
  features: Record<string, boolean>
}

export type ChatSession = {
  id: string
  title: string | null
  matter_id: string | null
  model: string | null
  member_id: string | null
  status: string
  created_at: string
  updated_at: string
}

export type Citation = {
  ref?: number
  document_id?: string
  chunk_id?: string
  title?: string
  snippet?: string
  matter_id?: string
  [key: string]: unknown
}

export type ChatEvent = { type: string; [key: string]: unknown }

/** A document attached to a user message. */
export type Attachment = { filename: string; document_id: string; content_type?: string }

/** One suggested change to a document, reviewed on a card in the chat. */
export type EditProposal = {
  id: string
  original: string
  proposed: string
  reason: string
  page: number | null
  located: boolean
  status: 'pending' | 'accepted' | 'rejected'
}

/** Question the assistant needs answered before it continues. */
export type AskInputItem = {
  id: string
  kind: 'choice' | 'text' | 'documents'
  question?: string
  options?: { value: string }[]
}

export type ChatMessage = {
  id?: string
  session_id?: string
  role: 'user' | 'assistant' | 'system'
  content: string
  events?: ChatEvent[] | null
  citations?: Citation[] | null
  files?: Attachment[] | null
  created_at?: string
}

export type ChatModel = { id: string; label: string; provider: string; default: boolean }

export type AskResult = {
  answer?: string
  key_finding?: string
  abstained?: boolean
  reason?: string
  structured_citations?: Array<Record<string, unknown>>
  sources?: Array<Record<string, unknown>>
  provider?: string
  [key: string]: unknown
}
