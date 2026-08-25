import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Button } from "@aiva/ui";
import { useAuth, signOut } from "./auth";
import { LoginPage } from "./pages/Login";
import { CandidatesPage } from "./pages/Candidates";
import { ResumeDetailPage } from "./pages/ResumeDetail";

function Shell({ children }: { children: React.ReactNode }) {
  return (
    <div className="min-h-screen bg-[var(--abyss)] text-[var(--mist)]">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--steel)] bg-[var(--hull)] px-6 py-3">
        <span className="display text-base font-bold tracking-widest text-[var(--signal-text)]">
          AIVA
        </span>
        <Button variant="ghost" onClick={signOut}>
          Sign out
        </Button>
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
        <Route path="*" element={<Navigate to="/pipeline" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
