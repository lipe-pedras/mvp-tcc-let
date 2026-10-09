import { NavLink, Navigate, Outlet, Route, Routes } from 'react-router-dom'
import { useAuth } from './auth'
import type { Role } from './api'
import Admin from './pages/Admin'
import Chat from './pages/Chat'
import Dashboard from './pages/Dashboard'
import DocEditor from './pages/DocEditor'
import DocList from './pages/DocList'
import DocView from './pages/DocView'
import Login from './pages/Login'
import Manage from './pages/Manage'

const ROLE_LABEL: Record<Role, string> = { admin: 'Admin', gestor: 'Gestor', colaborador: 'Colaborador' }

function Layout({ roles }: { roles?: Role[] }) {
  const { user, loading, logout } = useAuth()
  if (loading) return <p className="center muted">Carregando…</p>
  if (!user) return <Navigate to="/login" replace />
  if (roles && !roles.includes(user.role)) return <Navigate to="/" replace />
  const manager = user.role !== 'colaborador'
  return (
    <>
      <header className="topbar">
        <strong className="brand">Base de Conhecimento</strong>
        <nav>
          <NavLink to="/" end>Tutoriais</NavLink>
          <NavLink to="/assistente">Assistente</NavLink>
          {manager && <NavLink to="/gerenciar">Gerenciar documentos</NavLink>}
          {manager && <NavLink to="/painel">Painel</NavLink>}
          {user.role === 'admin' && <NavLink to="/admin">Administração</NavLink>}
        </nav>
        <span className="who">
          {user.name} <span className="badge">{ROLE_LABEL[user.role]}</span>
          <button className="link" onClick={logout}>Sair</button>
        </span>
      </header>
      <main><Outlet /></main>
    </>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route element={<Layout />}>
        <Route index element={<DocList />} />
        <Route path="docs/:id" element={<DocView />} />
        <Route path="assistente" element={<Chat />} />
      </Route>
      <Route element={<Layout roles={['admin', 'gestor']} />}>
        <Route path="gerenciar" element={<Manage />} />
        <Route path="gerenciar/:id" element={<DocEditor />} />
        <Route path="painel" element={<Dashboard />} />
      </Route>
      <Route element={<Layout roles={['admin']} />}>
        <Route path="admin" element={<Admin />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
