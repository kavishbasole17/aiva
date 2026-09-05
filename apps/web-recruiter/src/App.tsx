import { BrowserRouter, Link, Navigate, Route, Routes } from "react-router-dom";
import { Button, useTheme } from "@aiva/ui";
import { useAuth, signOut } from "./auth";
import { LoginPage } from "./pages/Login";
import { RequisitionsPage } from "./pages/Requisitions";
import { RequisitionDetailPage } from "./pages/RequisitionDetail";
import { ResumeUploadPage } from "./pages/ResumeUpload";
import { QuestionnairePage } from "./pages/Questionnaire";
import { SchedulingPage } from "./pages/Scheduling";
import { CandidatesPage } from "./pages/Candidates";
import { ResumeDetailPage } from "./pages/ResumeDetail";
import { SessionsPage } from "./pages/Sessions";
import { InterviewSessionDetailPage } from "./pages/InterviewSessionDetail";
import { DashboardPage } from "./pages/Dashboard";
import { MfaSetupPage } from "./pages/MfaSetup";

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button
      variant="ghost"
      onClick={toggle}
      aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}
    >
      {theme === "dark" ? "Light" : "Dark"} theme
    </Button>
  );
}

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--abyss)] text-[var(--mist)]">
      <header className="sticky top-0 z-10 border-b border-[var(--steel)] bg-[var(--hull)]">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-4">
          <div className="flex items-center gap-4">
            <span className="display text-lg font-bold tracking-tight text-[var(--signal)]">
              AIVA
            </span>
            <span className="hidden text-xs font-medium uppercase tracking-wide text-[var(--haze)] sm:inline">
              Recruiter Console
            </span>
            <nav className="hidden items-center gap-4 sm:flex">
              <Link
                to="/requisitions"
                className="text-sm text-[var(--haze)] hover:text-[var(--signal-text)]"
              >
                Requisitions
              </Link>
              <Link
                to="/dashboard"
                className="text-sm text-[var(--haze)] hover:text-[var(--signal-text)]"
              >
                Dashboard
              </Link>
              <Link
                to="/security"
                className="text-sm text-[var(--haze)] hover:text-[var(--signal-text)]"
              >
                Security
              </Link>
            </nav>
          </div>
          <div className="flex items-center gap-2">
            <ThemeToggle />
            <Button variant="ghost" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      {children}
    </div>
  );
}

function Protected({ children }: { children: React.ReactNode }) {
  const auth = useAuth();
  if (!auth.token) {
    return <Navigate to="/login" replace />;
  }
  return <Shell>{children}</Shell>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route
          path="/dashboard"
          element={
            <Protected>
              <DashboardPage />
            </Protected>
          }
        />
        <Route
          path="/requisitions"
          element={
            <Protected>
              <RequisitionsPage />
            </Protected>
          }
        />
        <Route
          path="/requisitions/:id"
          element={
            <Protected>
              <RequisitionDetailPage />
            </Protected>
          }
        />
        <Route
          path="/requisitions/:id/upload"
          element={
            <Protected>
              <ResumeUploadPage />
            </Protected>
          }
        />
        <Route
          path="/requisitions/:id/questionnaire"
          element={
            <Protected>
              <QuestionnairePage />
            </Protected>
          }
        />
        <Route
          path="/requisitions/:id/scheduling"
          element={
            <Protected>
              <SchedulingPage />
            </Protected>
          }
        />
        <Route
          path="/pipeline"
          element={
            <Protected>
              <CandidatesPage />
            </Protected>
          }
        />
        <Route
          path="/resumes/:id"
          element={
            <Protected>
              <ResumeDetailPage />
            </Protected>
          }
        />
        <Route
          path="/sessions"
          element={
            <Protected>
              <SessionsPage />
            </Protected>
          }
        />
        <Route
          path="/interview-sessions/:id"
          element={
            <Protected>
              <InterviewSessionDetailPage />
            </Protected>
          }
        />
        <Route
          path="/security"
          element={
            <Protected>
              <MfaSetupPage />
            </Protected>
          }
        />
        <Route path="*" element={<Navigate to="/requisitions" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
