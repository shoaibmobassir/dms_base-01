import { lazy, Suspense } from "react";
import { Routes, Route, Navigate, useLocation } from "react-router-dom";
import { AppShell } from "@/components/shell/AppShell";
import { HomePage } from "@/pages/HomePage";
import { TableSkeleton } from "@/components/common/primitives";
import { ErrorBoundary } from "@/components/common/ErrorBoundary";

// Each page loads when first opened, so the first screen does not carry the editor, chat or admin code.
const AdminPage = lazy(() => import("@/pages/AdminPage").then((m) => ({ default: m.AdminPage })));
const DocumentEditorPage = lazy(() => import("@/pages/DocumentEditorPage").then((m) => ({ default: m.DocumentEditorPage })));
const AskPage = lazy(() => import("@/pages/AskPage").then((m) => ({ default: m.AskPage })));
const ChatPage = lazy(() => import("@/pages/ChatPage").then((m) => ({ default: m.ChatPage })));
const MattersPage = lazy(() => import("@/pages/MattersPage").then((m) => ({ default: m.MattersPage })));
const MatterDetailPage = lazy(() => import("@/pages/MatterDetailPage").then((m) => ({ default: m.MatterDetailPage })));
const DocumentsPage = lazy(() => import("@/pages/DocumentsPage").then((m) => ({ default: m.DocumentsPage })));
const DocumentDetailPage = lazy(() => import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentDetailPage })));
const DocumentHistoryRedirect = lazy(() => import("@/pages/DocumentDetailPage").then((m) => ({ default: m.DocumentHistoryRedirect })));
const ClientsPage = lazy(() => import("@/pages/ClientsPage").then((m) => ({ default: m.ClientsPage })));
const ClientDetailPage = lazy(() => import("@/pages/ClientDetailPage").then((m) => ({ default: m.ClientDetailPage })));
const PeoplePage = lazy(() => import("@/pages/PeoplePage").then((m) => ({ default: m.PeoplePage })));
const PersonDetailPage = lazy(() => import("@/pages/PersonDetailPage").then((m) => ({ default: m.PersonDetailPage })));
const CalendarPage = lazy(() => import("@/pages/CalendarPage").then((m) => ({ default: m.CalendarPage })));
const ArgumentsPage = lazy(() => import("@/pages/ArgumentsPage").then((m) => ({ default: m.ArgumentsPage })));
const FullEditorPage = lazy(() => import("@/pages/FullEditorPage").then((m) => ({ default: m.FullEditorPage })));
const ProjectsPage = lazy(() => import("@/pages/ProjectsPage").then((m) => ({ default: m.ProjectsPage })));
const WorkbenchPage = lazy(() => import("@/pages/WorkbenchPage").then((m) => ({ default: m.WorkbenchPage })));
const SettingsPage = lazy(() => import("@/pages/SettingsPage").then((m) => ({ default: m.SettingsPage })));

function App() {
  const { pathname } = useLocation();
  return (
    <AppShell>
      <ErrorBoundary what="This page" resetKey={pathname}>
      <Suspense fallback={<div className="w-full px-6 py-8"><TableSkeleton /></div>}>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/ask/:answerId?" element={<AskPage />} />
        {/* One route so opening a new conversation's URL mid-answer doesn't remount the page. */}
        <Route path="/chat/:sessionId?" element={<ChatPage />} />
        <Route path="/assistant" element={<Navigate to="/chat" replace />} />
        <Route path="/matters" element={<MattersPage />} />
        <Route path="/matters/:id" element={<MatterDetailPage />} />
        <Route path="/projects" element={<ProjectsPage />} />
        <Route path="/work/:kind/:id" element={<WorkbenchPage />} />
        <Route path="/library" element={<Navigate to="/work/library/me" replace />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailPage />} />
        <Route path="/documents/:id/history" element={<DocumentHistoryRedirect />} />
        <Route path="/documents/:id/edit" element={<DocumentEditorPage />} />
        <Route path="/documents/:id/write" element={<FullEditorPage />} />
        <Route path="/clients" element={<ClientsPage />} />
        <Route path="/clients/:id" element={<ClientDetailPage />} />
        <Route path="/people" element={<PeoplePage />} />
        <Route path="/people/:id" element={<PersonDetailPage />} />
        <Route path="/calendar" element={<CalendarPage />} />
        <Route path="/deadlines" element={<Navigate to="/calendar" replace />} />
        <Route path="/arguments" element={<ArgumentsPage />} />
        <Route path="/teams" element={<Navigate to="/settings#teams" replace />} />
        <Route path="/settings" element={<SettingsPage />} />
        <Route path="/admin" element={<AdminPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
      </Suspense>
      </ErrorBoundary>
    </AppShell>
  );
}

export default App;
