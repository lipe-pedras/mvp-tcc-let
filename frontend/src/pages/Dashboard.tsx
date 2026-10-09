import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { api, fmtDate, type DocSummary, type Gaps, type Stats } from '../api'

const pct = (v: number | null) => (v === null ? '—' : `${Math.round(v * 100)}%`)

function Chart({ stats }: { stats: Stats }) {
  const max = Math.max(1, ...stats.per_day.map((d) => d.answered + d.refused))
  return (
    <>
      <div className="bars" role="img" aria-label="Perguntas por dia">
        {stats.per_day.map((d) => (
          <div className="bar" key={d.day} title={`${fmtDate(d.day)}: ${d.answered} respondidas, ${d.refused} sem resposta`}>
            <i className="a" style={{ height: `${(d.answered / max) * 90}px` }} />
            <i className="r" style={{ height: `${(d.refused / max) * 90}px` }} />
          </div>
        ))}
      </div>
      <div className="legend"><span style={{ color: 'var(--accent)' }}>■ respondidas</span><span style={{ color: 'var(--warn-line)' }}>■ sem resposta</span></div>
    </>
  )
}

export default function Dashboard() {
  const [days, setDays] = useState(30)
  const [stats, setStats] = useState<Stats | null>(null)
  const [gaps, setGaps] = useState<Gaps | null>(null)
  const [overdue, setOverdue] = useState<DocSummary[]>([])
  const [error, setError] = useState('')

  useEffect(() => {
    Promise.all([api<Stats>(`/manager/stats?days=${days}`), api<Gaps>(`/manager/gaps?days=${days}`)])
      .then(([s, g]) => { setStats(s); setGaps(g) }).catch((e) => setError(e.message))
  }, [days])
  useEffect(() => { api<DocSummary[]>('/manager/overdue-documents').then(setOverdue).catch(() => setOverdue([])) }, [])

  return (
    <>
      <div className="row">
        <h1 className="grow">Painel</h1>
        <select style={{ width: 'auto' }} value={days} onChange={(e) => setDays(Number(e.target.value))} aria-label="Período">
          <option value={7}>Últimos 7 dias</option><option value={30}>Últimos 30 dias</option><option value={90}>Últimos 90 dias</option>
        </select>
      </div>
      <p className="muted">Somente estatísticas agregadas. Conversas e identidades dos usuários não são armazenadas nem exibidas.</p>
      {error && <div className="error">{error}</div>}
      {stats && (
        <>
          <div className="grid">
            <div className="card stat">{stats.questions}<small>perguntas</small></div>
            <div className="card stat">{pct(stats.refusal_rate)}<small>taxa de recusa</small></div>
            <div className="card stat">{stats.feedback_negative}<small>“isso não respondeu” ({pct(stats.negative_feedback_rate)} do feedback)</small></div>
          </div>
          <div className="card"><strong>Perguntas por dia</strong><Chart stats={stats} /></div>
        </>
      )}
      <h2>Lacunas de documentação</h2>
      {gaps && (
        <>
          <p className="muted">
            Perguntas sem resposta agrupadas por similaridade. Um tema só aparece com pelo menos {gaps.min_occurrences} ocorrências,
            para que ninguém seja identificado por uma pergunta única.
            {gaps.hidden_gaps > 0 && ` ${gaps.hidden_gaps} pergunta(s) em temas com poucas ocorrências não são exibidas.`}
          </p>
          {gaps.clusters.length === 0 && <div className="card muted">Nenhum tema com {gaps.min_occurrences} ou mais ocorrências no período.</div>}
          {gaps.clusters.map((c) => (
            <div className="card" key={c.label}>
              <div className="row"><strong className="grow">{c.label}</strong><span className="badge bad">{c.count} ocorrências</span></div>
              <div className="muted" style={{ fontSize: '.85rem' }}>
                {fmtDate(c.first_day)} a {fmtDate(c.last_day)}{c.examples.length > 0 && <> · Variações: {c.examples.map((e) => `“${e}”`).join(', ')}</>}
              </div>
              <div style={{ marginTop: 8 }}><Link className="btn" to="/gerenciar/novo">Criar documento</Link></div>
            </div>
          ))}
        </>
      )}
      <h2>Revisões vencidas</h2>
      {overdue.length === 0 ? <div className="card muted">Nenhum documento com revisão vencida.</div> : (
        <table>
          <thead><tr><th>Documento</th><th>Revisão prevista</th><th>Responsável</th></tr></thead>
          <tbody>{overdue.map((d) => (
            <tr key={d.id}><td><Link to={`/gerenciar/${d.id}`}>{d.title}</Link></td><td>{fmtDate(d.review_date)}</td><td>{d.responsible?.name ?? '—'}</td></tr>
          ))}</tbody>
        </table>
      )}
    </>
  )
}
