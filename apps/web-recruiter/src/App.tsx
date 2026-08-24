import { Badge, Button, Card, EmptyState, Field, Input, PageStagger, ScoreRing, Skeleton, Textarea, useTheme } from "@aiva/ui";

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
          <span className="text-sm text-[var(--haze)]">Recruiter Console</span>
        </div>
        <ThemeToggle />
      </header>

      <main className="mx-auto flex max-w-5xl flex-col gap-12 px-6 py-12">
        <PageStagger>
          <section aria-labelledby="scores-heading" className="flex flex-col gap-4">
            <h1 id="scores-heading" className="display text-2xl font-semibold">
              Design system preview
            </h1>
            <p className="max-w-2xl text-sm text-[var(--haze)]">
              Milestone 1 deliverable: tokens, typography, and core components rendered
              in both themes. These score rings show sample values to exercise the
              component; no candidate data exists yet.
            </p>
          </section>

          <Card className="flex flex-wrap items-start gap-10">
            <ScoreRing score={87} label="Match" />
            <ScoreRing score={64} label="Technical" />
            <ScoreRing score={92} label="Overall" />
          </Card>

          <Card className="flex flex-col gap-6">
            <div className="flex flex-wrap items-center gap-2">
              <Badge tone="accent">Highly recommended</Badge>
              <Badge tone="positive">Recommended</Badge>
              <Badge tone="warning">Consider</Badge>
              <Badge tone="negative">Not recommended</Badge>
              <Badge>Hold</Badge>
            </div>

            <div className="flex flex-wrap gap-3">
              <Button>Shortlist</Button>
              <Button variant="action">Advance stage</Button>
              <Button variant="ghost">Compare</Button>
              <Button variant="danger">Reject</Button>
            </div>

            <div className="grid max-w-md gap-4">
              <Field label="Search candidates" htmlFor="demo-search" hint="Command palette arrives with the pipeline.">
                <Input id="demo-search" placeholder="Name, skill, or requisition" />
              </Field>
              <Field label="Recruiter notes" htmlFor="demo-notes">
                <Textarea id="demo-notes" placeholder="Evidence-linked notes land in Milestone 11." />
              </Field>
            </div>
          </Card>

          <Card className="flex flex-col gap-4">
            <h2 className="display text-lg font-semibold">Loading state</h2>
            <div className="grid gap-3">
              <Skeleton className="h-5 w-2/3" />
              <Skeleton className="h-5 w-1/2" />
              <Skeleton className="h-24 w-full" />
            </div>
          </Card>

          <EmptyState
            title="No requisitions yet"
            body="Requisitions appear here once org setup and resume ingest are delivered in later milestones."
          />
        </PageStagger>
      </main>
    </div>
  );
}
