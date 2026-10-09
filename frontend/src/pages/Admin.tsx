import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { api, type Group, type Role, type User } from '../api'

const ROLES: Role[] = ['colaborador', 'gestor', 'admin']

function UserRow({ u, groups, onChange }: { u: User; groups: Group[]; onChange: () => void }) {
  const [error, setError] = useState('')
  async function patch(body: Record<string, unknown>) {
    setError('')
    try { await api(`/users/${u.id}`, { method: 'PATCH', json: body }); onChange() } catch (e) { setError(e instanceof Error ? e.message : 'Erro') }
  }
  const ids = u.groups.map((g) => g.id)
  return (
    <tr>
      <td>{u.name}<div className="muted">{u.email}</div>{error && <div className="error">{error}</div>}</td>
      <td>
        <select value={u.role} onChange={(e) => patch({ role: e.target.value })} aria-label={`Papel de ${u.name}`}>
          {ROLES.map((r) => <option key={r}>{r}</option>)}
        </select>
      </td>
      <td>
        <div className="checks">
          {groups.map((g) => (
            <label key={g.id}>
              <input type="checkbox" checked={ids.includes(g.id)} onChange={() => patch({ group_ids: ids.includes(g.id) ? ids.filter((x) => x !== g.id) : [...ids, g.id] })} />
              {g.name}
            </label>
          ))}
        </div>
      </td>
      <td><button onClick={() => patch({ is_active: !u.is_active })}>{u.is_active ? 'Desativar' : 'Reativar'}</button></td>
    </tr>
  )
}

export default function Admin() {
  const [users, setUsers] = useState<User[]>([])
  const [groups, setGroups] = useState<Group[]>([])
  const [error, setError] = useState('')
  const [nu, setNu] = useState({ name: '', email: '', password: '', role: 'colaborador' as Role, group_ids: [] as number[] })
  const [groupName, setGroupName] = useState('')

  const load = useCallback(() => {
    api<User[]>('/users').then(setUsers).catch((e) => setError(e.message))
    api<Group[]>('/groups').then(setGroups)
  }, [])
  useEffect(load, [load])

  async function createUser(e: FormEvent) {
    e.preventDefault(); setError('')
    try {
      await api('/users', { method: 'POST', json: nu })
      setNu({ name: '', email: '', password: '', role: 'colaborador', group_ids: [] }); load()
    } catch (err) { setError(err instanceof Error ? err.message : 'Erro') }
  }
  async function createGroup(e: FormEvent) {
    e.preventDefault(); setError('')
    try { await api('/groups', { method: 'POST', json: { name: groupName } }); setGroupName(''); load() } catch (err) { setError(err instanceof Error ? err.message : 'Erro') }
  }

  return (
    <>
      <h1>Administração</h1>
      {error && <div className="error" role="alert">{error}</div>}
      <h2>Usuários</h2>
      <table>
        <thead><tr><th>Usuário</th><th>Papel</th><th>Grupos</th><th /></tr></thead>
        <tbody>{users.map((u) => <UserRow key={u.id} u={u} groups={groups} onChange={load} />)}</tbody>
      </table>
      <h2>Novo usuário</h2>
      <form className="card" onSubmit={createUser}>
        <div className="row">
          <div className="grow"><label htmlFor="n">Nome</label><input id="n" value={nu.name} onChange={(e) => setNu({ ...nu, name: e.target.value })} required /></div>
          <div className="grow"><label htmlFor="e">E-mail</label><input id="e" type="email" value={nu.email} onChange={(e) => setNu({ ...nu, email: e.target.value })} required /></div>
          <div className="grow"><label htmlFor="p">Senha (mín. 8)</label><input id="p" type="password" minLength={8} value={nu.password} onChange={(e) => setNu({ ...nu, password: e.target.value })} required /></div>
          <div><label htmlFor="r">Papel</label><select id="r" value={nu.role} onChange={(e) => setNu({ ...nu, role: e.target.value as Role })}>{ROLES.map((r) => <option key={r}>{r}</option>)}</select></div>
        </div>
        <label>Grupos</label>
        <div className="checks">
          {groups.map((g) => (
            <label key={g.id}><input type="checkbox" checked={nu.group_ids.includes(g.id)} onChange={() => setNu({ ...nu, group_ids: nu.group_ids.includes(g.id) ? nu.group_ids.filter((x) => x !== g.id) : [...nu.group_ids, g.id] })} />{g.name}</label>
          ))}
        </div>
        <p><button className="primary">Criar usuário</button></p>
      </form>
      <h2>Grupos</h2>
      <form className="card row" onSubmit={createGroup}>
        <div className="grow">{groups.map((g) => <span className="badge" style={{ marginRight: 6 }} key={g.id}>{g.name}</span>)}</div>
        <input style={{ width: 200 }} placeholder="Novo grupo" value={groupName} onChange={(e) => setGroupName(e.target.value)} required aria-label="Nome do novo grupo" />
        <button>Criar grupo</button>
      </form>
    </>
  )
}
