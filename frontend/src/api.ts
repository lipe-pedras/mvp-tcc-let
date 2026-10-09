// Thin typed client for the backend API.

export type Role = 'admin' | 'gestor' | 'colaborador'
export interface Group { id: number; name: string }
export interface Brief { id: number; name: string }
export interface User { id: number; name: string; email: string; role: Role; is_active: boolean; groups: Group[] }
export type DocStatus = 'draft' | 'published' | 'archived'
export interface DocSummary {
  id: number; title: string; status: DocStatus; current_version: number
  review_date: string | null; responsible: Brief | null; groups: Group[]; updated_at: string
}
export interface Doc extends DocSummary { author: Brief; content_md: string }
export interface Version { version: number; title: string; change_note: string | null; source: string; created_at: string }
export interface VersionDetail extends Version { content_md: string }
export interface Passage { chunk_id: number; section_path: string; version: number; is_current_version: boolean; text: string }

export interface Source {
  n: number; document_id: number; title: string; section_path: string
  version: number; chunk_id: number; page: number | null; review_overdue: boolean
}
export interface ChatResult {
  status: 'answered' | 'refused'
  answer: string
  sources: Source[]
  warnings: string[]
  responsible: { name: string; email: string; document_title: string } | null
  refusal_reason: string | null
}
export type Stage = 'retrieving' | 'generating' | 'validating'

export interface GapCluster { label: string; count: number; first_day: string; last_day: string; examples: string[] }
export interface Gaps { period_days: number; min_occurrences: number; total_gaps: number; hidden_gaps: number; clusters: GapCluster[] }
export interface DayStat { day: string; answered: number; refused: number; negative_feedback: number }
export interface Stats {
  period_days: number; questions: number; answered: number; refused: number; refusal_rate: number | null
  feedback_total: number; feedback_negative: number; negative_feedback_rate: number | null; per_day: DayStat[]
}

const TOKEN_KEY = 'kb_token'
export const tokenStore = {
  get(): string | null {
    try { return localStorage.getItem(TOKEN_KEY) } catch { return null }
  },
  set(t: string | null) {
    try {
      if (t) localStorage.setItem(TOKEN_KEY, t)
      else localStorage.removeItem(TOKEN_KEY)
    } catch { /* private mode */ }
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) { super(message); this.status = status }
}

let onUnauthorized: () => void = () => {}
export const setUnauthorizedHandler = (fn: () => void) => { onUnauthorized = fn }

function authHeaders(): Record<string, string> {
  const t = tokenStore.get()
  return t ? { Authorization: `Bearer ${t}` } : {}
}

async function fail(res: Response): Promise<never> {
  let detail = res.statusText
  try {
    const body = await res.json()
    detail = typeof body.detail === 'string' ? body.detail : JSON.stringify(body.detail)
  } catch { /* not JSON */ }
  if (res.status === 401 && tokenStore.get()) onUnauthorized()
  throw new ApiError(res.status, detail)
}

export async function api<T>(path: string, init: { method?: string; json?: unknown; form?: FormData } = {}): Promise<T> {
  const headers: Record<string, string> = { ...authHeaders() }
  let body: BodyInit | undefined
  if (init.json !== undefined) { headers['Content-Type'] = 'application/json'; body = JSON.stringify(init.json) }
  if (init.form) body = init.form
  const res = await fetch(`/api${path}`, { method: init.method ?? 'GET', headers, body })
  if (!res.ok) await fail(res)
  return res.status === 204 ? (undefined as T) : res.json()
}

export async function login(email: string, password: string): Promise<string> {
  const res = await fetch('/api/auth/login', { method: 'POST', body: new URLSearchParams({ username: email, password }) })
  if (!res.ok) await fail(res)
  return (await res.json()).access_token
}

/** POST /chat and read the Server-Sent Events: stage updates, then the final result. */
export async function askStream(question: string, onStage: (s: Stage) => void): Promise<ChatResult> {
  const res = await fetch('/api/chat', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...authHeaders() },
    body: JSON.stringify({ question }),
  })
  if (!res.ok || !res.body) await fail(res)
  const reader = res.body!.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let result: ChatResult | null = null
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let sep: number
    while ((sep = buffer.indexOf('\n\n')) >= 0) {
      const block = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)
      const event = /^event: (.*)$/m.exec(block)?.[1]
      const data = /^data: (.*)$/m.exec(block)?.[1]
      if (!event || !data) continue
      const payload = JSON.parse(data)
      if (event === 'stage') onStage(payload.name as Stage)
      else if (event === 'result') result = payload as ChatResult
      else if (event === 'error') throw new Error(payload.message)
    }
  }
  if (!result) throw new Error('A resposta terminou sem resultado.')
  return result
}

export const fmtDate = (iso: string | null): string => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—')
export const isOverdue = (iso: string | null): boolean => !!iso && iso < new Date().toISOString().slice(0, 10)
