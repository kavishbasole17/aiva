import { Badge, Button, Card, EmptyState, PageStagger, useTheme } from "@aiva/ui";

function ThemeToggle() {
  const { theme, toggle } = useTheme();
  return (
    <Button variant="ghost" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
      {theme === "dark" ? "Light" : "Dark"} theme
    </Button>
  );
}

export default function App() {
  return (
    <div className="min-h-screen bg-[var(--abyss)] text-[var(--mist)]">
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-[var(--steel)] bg-[var(--hull)] px-6 py-4">
        <div className="flex items-baseline gap-3">
          <span className="display text-lg font-bold tracking-widest text-[var(--signal-text)]">AIVA</span>
          <span className="text-sm text-[var(--haze)]">Candidate Journey</span>
        </div>
        <ThemeToggle />
      </header>

      <main className="mx-auto flex max-w-2xl flex-col gap-8 px-6 py-12">
        <PageStagger>
          <Card>
            <Badge tone="accent">Invitation required</Badge>
            <p className="mt-3 text-base leading-relaxed">
              When a hiring team invites you, your personal link opens this portal with
              your questionnaire and interview. Nothing about you is stored until you
              are invited.
            </p>
          </Card>

          <EmptyState
            title="Your interview opens here"
            body="Equipment checks, practice room, and the interview runner arrive in later milestones. You will always get a chance to test your camera and microphone first."
          />
        </PageStagger>
      </main>
    </div>
  );
}
