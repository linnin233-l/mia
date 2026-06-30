import { Routes, Route } from 'react-router-dom'
import MainLayout from './MainLayout'
import ChatPage from './pages/ChatPage'
import SessionsPage from './pages/SessionsPage'
import MemoryPage from './pages/MemoryPage'
import SettingsPage from './pages/SettingsPage'

export default function App() {
  return (
    <Routes>
      <Route element={<MainLayout />}>
        <Route path="/" element={<ChatPage />} />
        <Route path="/chat" element={<ChatPage />} />
        <Route path="/sessions" element={<SessionsPage />} />
        <Route path="/memory" element={<MemoryPage />} />
        <Route path="/settings" element={<SettingsPage />} />
      </Route>
    </Routes>
  )
}