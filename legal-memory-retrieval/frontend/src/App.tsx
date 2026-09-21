import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AppProvider } from './context/AppContext'
import { AppShell } from './layout/AppShell'
import { HomePage } from './pages/HomePage'
import { ChatPage } from './pages/ChatPage'
import { AskPage } from './pages/AskPage'
import { MattersPage } from './pages/MattersPage'
import { MatterDetailPage } from './pages/MatterDetailPage'
import { DocumentsPage } from './pages/DocumentsPage'
import { DocumentDetailPage } from './pages/DocumentDetailPage'
import { ClientsPage } from './pages/ClientsPage'
import { PeoplePage } from './pages/PeoplePage'
import {
  ActivityPage,
  ApprovalsPage,
  KnowledgePage,
  ProjectsPage,
  SettingsPage,
  SupportPage,
  TasksPage,
  TeamsPage,
} from './pages/SimplePages'
import './styles/global.css'

export default function App() {
  return (
    <AppProvider>
      <BrowserRouter basename="/ui">
        <Routes>
          <Route element={<AppShell />}>
            <Route index element={<HomePage />} />
            <Route path="chat" element={<ChatPage />} />
            <Route path="ask" element={<AskPage />} />
            <Route path="matters" element={<MattersPage />} />
            <Route path="matters/:matterId" element={<MatterDetailPage />} />
            <Route path="documents" element={<DocumentsPage />} />
            <Route path="documents/:documentId" element={<DocumentDetailPage />} />
            <Route path="clients" element={<ClientsPage />} />
            <Route path="clients/:clientId" element={<ClientsPage />} />
            <Route path="people" element={<PeoplePage />} />
            <Route path="people/:memberId" element={<PeoplePage />} />
            <Route path="projects" element={<ProjectsPage />} />
            <Route path="knowledge" element={<KnowledgePage />} />
            <Route path="teams" element={<TeamsPage />} />
            <Route path="activity" element={<ActivityPage />} />
            <Route path="tasks" element={<TasksPage />} />
            <Route path="approvals" element={<ApprovalsPage />} />
            <Route path="settings" element={<SettingsPage />} />
            <Route path="support" element={<SupportPage />} />
            <Route path="*" element={<Navigate to="/" replace />} />
          </Route>
        </Routes>
      </BrowserRouter>
    </AppProvider>
  )
}
