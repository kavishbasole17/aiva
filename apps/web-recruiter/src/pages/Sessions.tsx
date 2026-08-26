import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { Badge, Card, EmptyState, Skeleton } from "@aiva/ui";
import { listInterviewSessions, type InterviewSessionSummary } from "../api/client";

const STATUS_TONE: Record<string, "positive" | "accent" | "warning" | "negative" | "neutral"> = {
  active: "accent",
  completed: "positive",
  pending_consent: "neutral",
  consent_granted: "neutral",
  precheck_passed: "neutral",
  declined: "negative",
  aborted: "warning",
};

export function SessionsPage() {
  const [params] = useSearchParams();
  const requisitionId = params.get("req") ?? "";
  const [sessions, setSessions] = useState<InterviewSessionSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    document.title = "AIVA — Interview sessions";
  }, []);

  useEffect(() => {
    if (!requisitionId) return;
    let cancelled = false;
    setSessions(null);
    listInterviewSessions(requisitionId)
      .then((response) => {
        if (!cancelled) setSessions(response.sessions);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [requisitionId]);

  if (!requisitionId) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-[var(--mist)]">
        <EmptyState
          title="Open a requisition"
          body="Append ?req=<requisition-id> to this page, same as the pipeline view."
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <h1 className="display text-2xl font-semibold">Interview sessions</h1>
        <p className="mono mt-1 text-xs text-[var(--haze)]">requisition {requisitionId}</p>
      </header>

      {error ? (
        <Card>
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      {!sessions && !error ? (
        <div className="grid gap-3">
          <Skeleton className="h-16 w-full" />
          <Skeleton className="h-16 w-full" />
        </div>
      ) : null}

      {sessions?.length === 0 ? (
        <EmptyState
          title="No interview sessions yet"
          body="Book a slot from the pipeline and create a session against it through the API to see it here."
        />
      ) : null}

      <ul className="grid gap-3">
        {sessions?.map((session) => (
          <li key={session.id}>
            <Link to={`/interview-sessions/${session.id}`}>
              <Card interactive className="flex flex-wrap items-center justify-between gap-4 py-4">
                <div>
                  <p className="font-medium">{session.candidate_email}</p>
                  <p className="mono mt-1 text-xs text-[var(--haze)]">
                    {session.turn_count} turns
                    {session.started_at ? ` · started ${new Date(session.started_at).toLocaleString()}` : ""}
                  </p>
                </div>
                <Badge tone={STATUS_TONE[session.status] ?? "neutral"}>
                  {session.status.replaceAll("_", " ")}
                </Badge>
              </Card>
            </Link>
          </li>
        ))}
      </ul>
    </main>
  );
}
