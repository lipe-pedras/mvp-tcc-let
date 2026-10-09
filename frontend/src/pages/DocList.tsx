import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, isOverdue, type DocSummary } from '../api'

export default function DocList() {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [q, setQ] = useState('')
  const [error, setError] = useState('')

  useEffect(() => { api<DocSummary[]>('/documents').then(setDocs).catch((e) => setError(e.message)) }, [])

  const shown = (docs ?? []).filter((d) => d.title.toLowerCase().includes(q.toLowerCase()))
  return (
    <>
      <h1>Tutoriais</h1>
      <input placeholder="Filtrar por título…" value={q} onChange={(e) => setQ(e.target.value)} aria-label="Filtrar tutoriais" />
      {error && <div className="error">{error}</div>}
      {docs === null && !error && <p className="muted">Carregando…</p>}
      {docs && shown.length === 0 && <p className="muted">Nenhum tutorial encontrado.</p>}
      <div style={{ marginTop: 16 }}>
        {shown.map((d) => (
          <div className="card" key={d.id}>
            <div className="row">
              <Link className="grow" to={`/docs/${d.id}`}><strong>{d.title}</strong></Link>
              {isOverdue(d.review_date) && <span className="badge warn">revisão vencida</span>}
              {d.status !== 'published' && <span className="badge">{d.status === 'draft' ? 'rascunho' : 'arquivado'}</span>}
            </div>
            <div className="muted" style={{ fontSize: '.85rem', marginTop: 4 }}>
              Responsável: {d.responsible?.name ?? '—'} · Revisão: {fmtDate(d.review_date)} · Versão {d.current_version}
            </div>
          </div>
        ))}
      </div>
    </>
  )
}
