import { useEffect, useState } from "react";
import { Card, EmptyState, Skeleton } from "@aiva/ui";
import { getDashboard, getMe, type DashboardStats } from "../api/client";

function StatTile({ label, value }: { label: string; value: string | number }) {
  return (
    <Card>
      <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haze)]">{label}</p>
      <p className="data-value mt-2 text-3xl font-semibold">{value}</p>
    </Card>
  );
}

function BreakdownCard({
  title,
  counts,
}: {
  title: string;
  counts: Record<string, number>;
}) {
  const total = Object.values(counts).reduce((sum, n) => sum + n, 0);
  const entries = Object.entries(counts).sort(([, a], [, b]) => b - a);
  return (
    <Card>
      <p className="mb-3 text-sm font-semibold">{title}</p>
      {entries.length === 0 ? (
        <p className="text-sm text-[var(--haze)]">No data yet.</p>
      ) : (
        <ul className="flex flex-col gap-2">
          {entries.map(([key, count]) => (
            <li key={key} className="flex items-center gap-3">
              <span className="w-40 shrink-0 text-sm capitalize">
                {key.replaceAll("_", " ")}
              </span>
              <div className="h-2 flex-1 overflow-hidden rounded-full bg-[var(--steel)]">
                <div
                  className="h-full rounded-full bg-[var(--signal)]"
                  style={{ width: total ? `${(count / total) * 100}%` : "0%" }}
                />
              </div>
              <span className="data-value w-8 text-right text-sm">{count}</span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

export function DashboardPage() {
  const [stats, setStats] = useState<DashboardStats | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "AIVA — Dashboard";
  }, []);

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((me) => getDashboard(me.organization_id))
      .then((response) => {
        if (!cancelled) setStats(response);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, []);

  if (error) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-16 text-[var(--mist)]">
        <EmptyState title="Could not load dashboard" body={error} />
      </main>
    );
  }

  if (!stats) {
    return (
      <main className="mx-auto max-w-5xl px-6 py-10">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </div>
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-[var(--mist)]">
      <h1 className="display mb-8 text-2xl font-semibold">Dashboard</h1>

      <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
        <StatTile label="Open requisitions" value={stats.requisitions.open} />
        <StatTile label="Resumes" value={stats.resumes.total} />
        <StatTile
          label="Questionnaire submission rate"
          value={
            stats.questionnaires.submission_rate === null
              ? "—"
              : `${Math.round(stats.questionnaires.submission_rate * 100)}%`
          }
        />
        <StatTile
          label="Coding pass rate"
          value={
            stats.coding_tasks.pass_rate === null
              ? "—"
              : `${Math.round(stats.coding_tasks.pass_rate * 100)}%`
          }
        />
      </div>

      <div className="mt-6 grid gap-4 md:grid-cols-2">
        <BreakdownCard title="Requisitions by status" counts={stats.requisitions.by_status} />
        <BreakdownCard title="Scoring verdicts" counts={stats.scoring.by_verdict} />
        <BreakdownCard title="Interview sessions by status" counts={stats.interviews.by_status} />
      </div>
    </main>
  );
}
