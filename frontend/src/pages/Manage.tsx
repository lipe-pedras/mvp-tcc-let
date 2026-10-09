import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, isOverdue, type DocSummary } from '../api'

const STATUS = { draft: 'rascunho', published: 'publicado', archived: 'arquivado' } as const

export default function Manage() {
  const [docs, setDocs] = useState<DocSummary[] | null>(null)
  const [error, setError] = useState('')
  useEffect(() => { api<DocSummary[]>('/documents').then(setDocs).catch((e) => setError(e.message)) }, [])

  return (
    <>
      <div className="row">
        <h1 className="grow">Gerenciar documentos</h1>
        <Link className="btn primary" to="/gerenciar/novo">Novo documento</Link>
        <Link className="btn" to="/gerenciar/importar">Importar arquivo</Link>
      </div>
      {error && <div className="error">{error}</div>}
      {docs === null && !error && <p className="muted">Carregando…</p>}
      {docs && (
        <table>
          <thead><tr><th>Título</th><th>Status</th><th>Grupos</th><th>Responsável</th><th>Revisão</th><th>Versão</th></tr></thead>
          <tbody>
            {docs.map((d) => (
              <tr key={d.id}>
                <td><Link to={`/gerenciar/${d.id}`}>{d.title}</Link></td>
                <td><span className="badge">{STATUS[d.status]}</span></td>
                <td>{d.groups.map((g) => g.name).join(', ')}</td>
                <td>{d.responsible?.name ?? '—'}</td>
                <td>{fmtDate(d.review_date)} {isOverdue(d.review_date) && <span className="badge warn">vencida</span>}</td>
                <td>{d.current_version}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </>
  )
}
