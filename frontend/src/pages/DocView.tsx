import { useEffect, useState } from 'react'
import { Link, useParams, useSearchParams } from 'react-router-dom'
import { api, fmtDate, isOverdue, type Doc, type Passage } from '../api'
import Markdown from '../components/Markdown'
import { slug } from '../components/slug'

function DocViewInner({ id, chunk }: { id: string; chunk: string | null }) {
  const [doc, setDoc] = useState<Doc | null>(null)
  const [passage, setPassage] = useState<Passage | null>(null)
  const [error, setError] = useState('')

  useEffect(() => {
    api<Doc>(`/documents/${id}`).then(setDoc).catch((e) => setError(e.message))
    if (chunk) api<Passage>(`/documents/${id}/passages/${chunk}`).then(setPassage).catch(() => setPassage(null))
  }, [id, chunk])

  // Highlight the cited section's heading in the full document (the passage box stays in view).
  useEffect(() => {
    if (!doc || !passage) return
    const last = passage.section_path.split(' > ').pop()
    document.getElementById(last ? slug(last) : '')?.classList.add('flash')
  }, [doc, passage])

  const jumpToSection = () => {
    const last = passage?.section_path.split(' > ').pop()
    document.getElementById(last ? slug(last) : '')?.scrollIntoView({ block: 'start', behavior: 'smooth' })
  }

  if (error) return <div className="error">{error}</div>
  if (!doc) return <p className="muted">Carregando…</p>
  return (
    <>
      <p><Link to="/">← Tutoriais</Link></p>
      <h1>{doc.title}</h1>
      <p className="muted">
        Responsável pelo tema: {doc.responsible ? `${doc.responsible.name}` : '—'} · Revisão: {fmtDate(doc.review_date)} · Versão {doc.current_version}
      </p>
      {isOverdue(doc.review_date) && (
        <div className="warning">Este tutorial está com a revisão vencida desde {fmtDate(doc.review_date)}; a informação pode estar desatualizada.</div>
      )}
      {passage && (
        <aside className="passage" aria-label="Trecho citado">
          <strong>Trecho citado</strong>{passage.section_path && <> — {passage.section_path}</>} <span className="badge">versão {passage.version}</span>{' '}
          {passage.is_current_version && <button className="link" onClick={jumpToSection}>Ver no documento</button>}
          {!passage.is_current_version && (
            <div className="warning">Este trecho vem da versão {passage.version}; o tutorial já foi atualizado (versão atual: {doc.current_version}).</div>
          )}
          <Markdown>{passage.text}</Markdown>
        </aside>
      )}
      <div className="card"><Markdown>{doc.content_md}</Markdown></div>
    </>
  )
}

export default function DocView() {
  const { id = '' } = useParams()
  const [params] = useSearchParams()
  const chunk = params.get('chunk')
  return <DocViewInner key={`${id}|${chunk}`} id={id} chunk={chunk} />
}
