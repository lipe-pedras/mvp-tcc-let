import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { api, type Brief, type Doc, type DocStatus, type Group, type Version, type VersionDetail } from '../api'
import Markdown from '../components/Markdown'

interface Form {
  title: string; content_md: string; responsible_id: string; review_date: string
  group_ids: number[]; status: DocStatus; change_note: string
}
const EMPTY: Form = { title: '', content_md: '', responsible_id: '', review_date: '', group_ids: [], status: 'published', change_note: '' }

function VersionHistory({ docId, onLoad }: { docId: number; onLoad: (v: VersionDetail) => void }) {
  const [versions, setVersions] = useState<Version[]>([])
  useEffect(() => { api<Version[]>(`/documents/${docId}/versions`).then(setVersions).catch(() => setVersions([])) }, [docId])
  return (
    <>
      <h2>Histórico de versões</h2>
      <table>
        <thead><tr><th>Versão</th><th>Data</th><th>Nota</th><th /></tr></thead>
        <tbody>
          {versions.map((v) => (
            <tr key={v.version}>
              <td>v{v.version}</td>
              <td>{v.created_at.slice(0, 16).replace('T', ' ')}</td>
              <td>{v.change_note ?? (v.source === 'import' ? 'importado' : '')}</td>
              <td><button className="link" onClick={async () => onLoad(await api<VersionDetail>(`/documents/${docId}/versions/${v.version}`))}>Carregar no editor</button></td>
            </tr>
          ))}
        </tbody>
      </table>
    </>
  )
}

function DocEditorInner({ id }: { id: string }) {
  const navigate = useNavigate()
  const mode = id === 'novo' ? 'new' : id === 'importar' ? 'import' : 'edit'
  const [form, setForm] = useState<Form>(EMPTY)
  const [original, setOriginal] = useState<Doc | null>(null)
  const [file, setFile] = useState<File | null>(null)
  const [groups, setGroups] = useState<Group[]>([])
  const [people, setPeople] = useState<Brief[]>([])
  const [preview, setPreview] = useState(false)
  const [error, setError] = useState('')
  const [saved, setSaved] = useState('')
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api<Group[]>('/groups').then(setGroups)
    api<Brief[]>('/people').then(setPeople)
  }, [])

  useEffect(() => {
    if (mode !== 'edit') return
    api<Doc>(`/documents/${id}`).then((d) => {
      setOriginal(d)
      setForm({
        title: d.title, content_md: d.content_md, responsible_id: d.responsible ? String(d.responsible.id) : '',
        review_date: d.review_date ?? '', group_ids: d.groups.map((g) => g.id), status: d.status, change_note: '',
      })
    }).catch((e) => setError(e.message))
  }, [id, mode])

  const set = <K extends keyof Form>(k: K, v: Form[K]) => setForm((f) => ({ ...f, [k]: v }))
  const toggleGroup = (gid: number) => set('group_ids', form.group_ids.includes(gid) ? form.group_ids.filter((x) => x !== gid) : [...form.group_ids, gid])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(''); setSaved('')
    if (form.group_ids.length === 0) { setError('Escolha pelo menos um grupo com acesso.'); return }
    setBusy(true)
    try {
      const responsible_id = form.responsible_id ? Number(form.responsible_id) : null
      const review_date = form.review_date || null
      if (mode === 'import') {
        if (!file) { setError('Escolha um arquivo PDF, DOCX ou PPTX.'); return }
        const fd = new FormData()
        fd.append('file', file); fd.append('title', form.title); fd.append('status', form.status)
        form.group_ids.forEach((g) => fd.append('group_ids', String(g)))
        if (responsible_id) fd.append('responsible_id', String(responsible_id))
        if (review_date) fd.append('review_date', review_date)
        const doc = await api<Doc>('/documents/import', { method: 'POST', form: fd })
        navigate(`/gerenciar/${doc.id}`)
      } else if (mode === 'new') {
        const doc = await api<Doc>('/documents', { method: 'POST', json: { title: form.title, content_md: form.content_md, responsible_id, review_date, group_ids: form.group_ids, status: form.status } })
        navigate(`/gerenciar/${doc.id}`)
      } else if (original) {
        // Send only what changed: unchanged content must not create a version or trigger reindexing.
        const body: Record<string, unknown> = {}
        if (form.title !== original.title) body.title = form.title
        if (form.content_md !== original.content_md) body.content_md = form.content_md
        if (responsible_id !== (original.responsible?.id ?? null)) body.responsible_id = responsible_id
        if (review_date !== original.review_date) body.review_date = review_date
        if (form.status !== original.status) body.status = form.status
        const before = original.groups.map((g) => g.id).sort().join()
        if (form.group_ids.slice().sort().join() !== before) body.group_ids = form.group_ids
        if (form.change_note) body.change_note = form.change_note
        const doc = await api<Doc>(`/documents/${id}`, { method: 'PUT', json: body })
        setOriginal(doc)
        set('change_note', '')
        setSaved(`Salvo. Versão atual: ${doc.current_version}.`)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Erro ao salvar')
    } finally {
      setBusy(false)
    }
  }

  async function archive() {
    if (!confirm('Arquivar este documento? Ele deixa de aparecer no chat e para os colaboradores; o histórico é mantido.')) return
    await api(`/documents/${id}`, { method: 'DELETE' })
    navigate('/gerenciar')
  }

  const title = mode === 'new' ? 'Novo documento' : mode === 'import' ? 'Importar arquivo' : 'Editar documento'
  return (
    <>
      <p><Link to="/gerenciar">← Documentos</Link></p>
      <h1>{title}</h1>
      <form onSubmit={submit}>
        <div className="card">
          <label htmlFor="title">Título</label>
          <input id="title" value={form.title} onChange={(e) => set('title', e.target.value)} required />
          <div className="row">
            <div className="grow">
              <label htmlFor="resp">Responsável pelo tema</label>
              <select id="resp" value={form.responsible_id} onChange={(e) => set('responsible_id', e.target.value)}>
                <option value="">— ninguém —</option>
                {people.map((p) => <option key={p.id} value={p.id}>{p.name}</option>)}
              </select>
            </div>
            <div className="grow">
              <label htmlFor="rev">Data de revisão</label>
              <input id="rev" type="date" value={form.review_date} onChange={(e) => set('review_date', e.target.value)} />
            </div>
            <div className="grow">
              <label htmlFor="status">Status</label>
              <select id="status" value={form.status} onChange={(e) => set('status', e.target.value as DocStatus)}>
                <option value="published">Publicado</option><option value="draft">Rascunho</option><option value="archived">Arquivado</option>
              </select>
            </div>
          </div>
          <label>Grupos com acesso</label>
          <div className="checks">
            {groups.map((g) => (
              <label key={g.id}><input type="checkbox" checked={form.group_ids.includes(g.id)} onChange={() => toggleGroup(g.id)} />{g.name}</label>
            ))}
          </div>
        </div>
        {mode === 'import' ? (
          <div className="card">
            <label htmlFor="file">Arquivo (PDF, DOCX ou PPTX)</label>
            <input id="file" type="file" accept=".pdf,.docx,.pptx" onChange={(e) => setFile(e.target.files?.[0] ?? null)} />
            <p className="muted">O conteúdo é convertido para Markdown (tabelas incluídas). Revise o resultado antes de publicar.</p>
          </div>
        ) : (
          <div className="card">
            <div className="row">
              <label className="grow" htmlFor="content">Conteúdo (Markdown)</label>
              <button type="button" className="link" onClick={() => setPreview(!preview)}>{preview ? 'Editar' : 'Pré-visualizar'}</button>
            </div>
            {preview ? <Markdown>{form.content_md}</Markdown> : <textarea id="content" value={form.content_md} onChange={(e) => set('content_md', e.target.value)} required />}
            {mode === 'edit' && (
              <>
                <label htmlFor="note">Nota da alteração (opcional)</label>
                <input id="note" value={form.change_note} onChange={(e) => set('change_note', e.target.value)} maxLength={255} />
              </>
            )}
          </div>
        )}
        {error && <div className="error" role="alert">{error}</div>}
        {saved && <div className="notice" role="status">{saved}</div>}
        <div className="row">
          <button className="primary" disabled={busy}>{busy ? 'Salvando…' : mode === 'import' ? 'Importar' : 'Salvar'}</button>
          {mode === 'edit' && <button type="button" className="danger" onClick={archive}>Arquivar</button>}
        </div>
      </form>
      {mode === 'edit' && original && <VersionHistory key={original.current_version} docId={original.id} onLoad={(v) => { set('title', v.title); set('content_md', v.content_md); setSaved(`Versão ${v.version} carregada no editor; salve para criar uma nova versão com este conteúdo.`) }} />}
    </>
  )
}

export default function DocEditor() {
  const { id = '' } = useParams()
  return <DocEditorInner key={id} id={id} />
}
