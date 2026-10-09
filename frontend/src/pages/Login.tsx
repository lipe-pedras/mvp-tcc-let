import { useState, type FormEvent } from 'react'
import { Navigate } from 'react-router-dom'
import { useAuth } from '../auth'

export default function Login() {
  const { user, login } = useAuth()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  if (user) return <Navigate to="/" replace />

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true); setError('')
    try { await login(email, password) } catch (err) { setError(err instanceof Error ? err.message : 'Falha no login') } finally { setBusy(false) }
  }

  return (
    <form className="card login" onSubmit={submit}>
      <h1>Base de Conhecimento</h1>
      <p className="muted">Entre para consultar os tutoriais e o assistente.</p>
      <label htmlFor="email">E-mail</label>
      <input id="email" type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoFocus />
      <label htmlFor="password">Senha</label>
      <input id="password" type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
      {error && <div className="error">{error}</div>}
      <p><button className="primary" disabled={busy}>{busy ? 'Entrando…' : 'Entrar'}</button></p>
      <p className="hint">Ambiente de exemplo: novato@alvorada.example / senha-12345</p>
    </form>
  )
}
