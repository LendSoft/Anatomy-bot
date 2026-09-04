import { useEffect } from 'react'
import { Navigate, Route, Routes } from 'react-router-dom'
import { Spin } from 'antd'

import AdminLayout from './components/AdminLayout'
import Login from './pages/Login'
import Dashboard from './pages/Dashboard'
import Documents from './pages/Documents'
import Images from './pages/Images'
import Prompts from './pages/Prompts'
import Settings from './pages/Settings'
import Playground from './pages/Playground'
import Logs from './pages/Logs'
import Testing from './pages/Testing'
import Glossary from './pages/Glossary'
import System from './pages/System'
import { useAuthStore } from './store/auth'

function RequireAuth({ children }) {
  const { user, loading } = useAuthStore()

  if (loading) {
    return (
      <div style={{ display: 'grid', placeItems: 'center', height: '100vh' }}>
        <Spin size="large" />
      </div>
    )
  }

  return user ? children : <Navigate to="/login" replace />
}

export default function App() {
  const init = useAuthStore((state) => state.init)

  useEffect(() => {
    init()
  }, [init])

  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <RequireAuth>
            <AdminLayout />
          </RequireAuth>
        }
      >
        <Route index element={<Dashboard />} />
        <Route path="documents" element={<Documents />} />
        <Route path="images" element={<Images />} />
        <Route path="prompts" element={<Prompts />} />
        <Route path="settings" element={<Settings />} />
        <Route path="playground" element={<Playground />} />
        <Route path="logs" element={<Logs />} />
        <Route path="testing" element={<Testing />} />
        <Route path="glossary" element={<Glossary />} />
        <Route path="system" element={<System />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
