import { Badge, Button } from "@aiva/ui";
import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import Interview from "./pages/Interview";
import Join from "./pages/Join";
import { useTheme } from "@aiva/ui";

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

export default function App() {
  return (
    <BrowserRouter>
      <div className="min-h-screen bg-[var(--abyss)] text-[var(--mist)]">
        <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--steel)] bg-[var(--hull)] px-6 py-4">
          <div className="flex items-baseline gap-3">
            <span className="display text-lg font-bold tracking-widest text-[var(--signal-text)]">
              AIVA
            </span>
            <span className="text-sm text-[var(--haze)]">Candidate Portal</span>
          </div>
          <div className="flex items-center gap-3">
            <Badge tone="neutral">Air-gapped session</Badge>
            <ThemeToggle />
          </div>
        </header>

        <Routes>
          <Route path="/" element={<Join />} />
          <Route path="/interview" element={<Interview />} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>

        <footer className="mx-auto max-w-2xl px-6 pb-10 pt-4">
          <p className="text-center text-xs text-[var(--haze)]">
            Your session runs entirely on this organization&apos;s infrastructure. No external
            services are contacted at any point.
          </p>
        </footer>
      </div>
    </BrowserRouter>
  );
}
