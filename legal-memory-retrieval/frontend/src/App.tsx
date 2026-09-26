import { Routes, Route, Navigate } from "react-router-dom";
import { AdminPage } from "@/pages/AdminPage";
import { AppShell } from "@/components/shell/AppShell";
import { HomePage } from "@/pages/HomePage";
import { AskPage } from "@/pages/AskPage";
import { ChatPage } from "@/pages/ChatPage";
import { MattersPage } from "@/pages/MattersPage";
import { MatterDetailPage } from "@/pages/MatterDetailPage";
import { DocumentsPage } from "@/pages/DocumentsPage";
import { DocumentDetailPage, DocumentHistoryRedirect } from "@/pages/DocumentDetailPage";
import { ClientsPage } from "@/pages/ClientsPage";
import { ClientDetailPage } from "@/pages/ClientDetailPage";
import { PeoplePage } from "@/pages/PeoplePage";
import { PersonDetailPage } from "@/pages/PersonDetailPage";
import { CalendarPage } from "@/pages/CalendarPage";
import { ArgumentsPage } from "@/pages/ArgumentsPage";
import { SettingsPage } from "@/pages/SettingsPage";

function App() {
  return (
    <AppShell>
      <Routes>
        <Route path="/" element={<HomePage />} />
        <Route path="/ask" element={<AskPage />} />
        {/* One route so opening a new conversation's URL mid-answer doesn't remount the page. */}
        <Route path="/chat/:sessionId?" element={<ChatPage />} />
        <Route path="/assistant" element={<Navigate to="/chat" replace />} />
        <Route path="/matters" element={<MattersPage />} />
        <Route path="/matters/:id" element={<MatterDetailPage />} />
        <Route path="/documents" element={<DocumentsPage />} />
        <Route path="/documents/:id" element={<DocumentDetailPage />} />
        <Route path="/documents/:id/history" element={<DocumentHistoryRedirect />} />
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
    </AppShell>
  );
}

export default App;
