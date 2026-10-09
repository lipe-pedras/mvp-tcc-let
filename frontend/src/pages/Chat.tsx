import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { api, askStream, type ChatResult, type Stage } from '../api'
import Markdown from '../components/Markdown'

// While the answer is generated and validated (it is only shown once verified),
// the user sees these messages, rotating inside each stage.
const PHRASES: Record<Stage, string[]> = {
  retrieving: ['Coletando informações no banco de dados...', 'Consultando a documentação...'],
  generating: ['Gerando resposta...', 'Organizando as informações encontradas...'],
  validating: ['Validando conteúdo...', 'Verificando a veracidade...', 'Conferindo as fontes citadas...'],
}

interface Turn { question: string; result: ChatResult | null; error?: string; feedback?: 'sent' | 'error' }

function Thinking({ stage }: { stage: Stage }) {
  const [i, setI] = useState(0)
  useEffect(() => {
    const t = setInterval(() => setI((n) => n + 1), 2600)
    return () => clearInterval(t)
  }, [])
  const list = PHRASES[stage]
  return (
    <div className="thinking card" role="status" aria-live="polite">
      <span className="spinner" aria-hidden />
      <span>{list[i % list.length]}</span>
    </div>
  )
}

/** Turn "[1]" and "[1, 2]" into clickable citation links before rendering Markdown. */
function linkCitations(text: string): string {
  return text.replace(/\[(\d+(?:\s*,\s*\d+)*)\]/g, (_m, nums: string) =>
    nums.split(',').map((n) => `[${n.trim()}](#cite-${n.trim()})`).join(''))
}

function Answer({ turn, onFeedback }: { turn: Turn; onFeedback: (helpful: boolean) => void }) {
  const r = turn.result!
  const byN = new Map(r.sources.map((s) => [s.n, s]))
  const href = (n: number) => { const s = byN.get(n); return s ? `/docs/${s.document_id}?chunk=${s.chunk_id}` : '/' }

  if (r.status === 'refused') {
    return (
      <div className="card">
        <p><strong>{r.answer}</strong></p>
        {r.responsible && (
          <p>Quem pode ajudar: <strong>{r.responsible.name}</strong> ({r.responsible.email}), responsável por “{r.responsible.document_title}”.</p>
        )}
        <p className="muted" style={{ fontSize: '.85rem' }}>Esta pergunta foi registrada, de forma anônima, como lacuna para a equipe documentar.</p>
      </div>
    )
  }
  return (
    <div className="card">
      <Markdown components={{
        a: ({ href: h, children }: { href?: string; children?: React.ReactNode }) => {
          const n = /^#cite-(\d+)$/.exec(h ?? '')?.[1]
          return n ? <Link className="cite" to={href(+n)} target="_blank" rel="noopener" title={byN.get(+n)?.title}>{children}</Link> : <a href={h}>{children}</a>
        },
      }}>{linkCitations(r.answer)}</Markdown>
      {r.warnings.map((w) => <div className="warning" key={w}>⚠ {w}</div>)}
      <div className="sources">
        Fontes:{' '}
        {r.sources.map((s) => (
          <Link key={s.n} to={href(s.n)} target="_blank" rel="noopener">[{s.n}] {s.title}{s.section_path && ` › ${s.section_path}`} (v{s.version})</Link>
        ))}
      </div>
      <div className="actions">
        {turn.feedback === 'sent' ? <span className="muted">Obrigado! Seu retorno foi registrado de forma anônima.</span> : (
          <>
            <button onClick={() => onFeedback(true)}>Útil</button>
            <button onClick={() => onFeedback(false)}>Isso não respondeu</button>
            {turn.feedback === 'error' && <span className="muted">Não foi possível enviar. Tente novamente.</span>}
          </>
        )}
      </div>
    </div>
  )
}

export default function Chat() {
  const [turns, setTurns] = useState<Turn[]>([])
  const [question, setQuestion] = useState('')
  const [stage, setStage] = useState<Stage | null>(null)
  const bottom = useRef<HTMLDivElement>(null)

  useEffect(() => { bottom.current?.scrollIntoView({ behavior: 'smooth' }) }, [turns, stage])

  async function submit(e: FormEvent) {
    e.preventDefault()
    const q = question.trim()
    if (!q || stage) return
    setQuestion('')
    setTurns((t) => [...t, { question: q, result: null }])
    setStage('retrieving')
    const patch = (p: Partial<Turn>) => setTurns((t) => t.map((x, i) => (i === t.length - 1 ? { ...x, ...p } : x)))
    try {
      patch({ result: await askStream(q, setStage) })
    } catch (err) {
      patch({ error: err instanceof Error ? err.message : 'Erro ao consultar o assistente.' })
    } finally {
      setStage(null)
    }
  }

  async function feedback(index: number, helpful: boolean) {
    const t = turns[index]
    if (!t.result) return
    try {
      await api('/chat/feedback', { method: 'POST', json: { question: t.question, answer: t.result.answer, helpful } })
      setTurns((all) => all.map((x, i) => (i === index ? { ...x, feedback: 'sent' } : x)))
    } catch {
      setTurns((all) => all.map((x, i) => (i === index ? { ...x, feedback: 'error' } : x)))
    }
  }

  return (
    <>
      <h1>Assistente</h1>
      <p className="muted">Responde somente com base na documentação interna que você tem permissão de ver, sempre citando a fonte. As conversas não são armazenadas.</p>
      <div className="chat">
        {turns.map((t, i) => (
          <div key={i} className="chat">
            <div className="msg-user">{t.question}</div>
            <div className="msg-bot">
              {t.error && <div className="error">{t.error}</div>}
              {t.result && <Answer turn={t} onFeedback={(h) => feedback(i, h)} />}
              {!t.result && !t.error && stage && i === turns.length - 1 && <Thinking key={stage} stage={stage} />}
            </div>
          </div>
        ))}
        <div ref={bottom} />
      </div>
      <form className="composer" onSubmit={submit}>
        <input value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Pergunte sobre processos, sistemas, benefícios…" maxLength={1000} aria-label="Pergunta" />
        <button className="primary" disabled={!!stage || !question.trim()}>Perguntar</button>
      </form>
    </>
  )
}
