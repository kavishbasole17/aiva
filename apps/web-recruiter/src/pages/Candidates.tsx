import { useEffect, useMemo, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { motion } from "motion/react";
import { Badge, Button, Card, EmptyState, Input, Skeleton } from "@aiva/ui";
import { listCandidates, type CandidateSummary } from "../api/client";

const VERDICT_ORDER: Record<string, number> = {
  highly_recommended: 0,
  shortlist: 1,
  hold: 2,
  auto_reject: 3,
};

const VERDICT_TONE: Record<string, "positive" | "accent" | "warning" | "negative"> = {
  highly_recommended: "accent",
  shortlist: "positive",
  hold: "warning",
  auto_reject: "negative",
};

const VERDICT_LABEL: Record<string, string> = {
  highly_recommended: "Highly recommended",
  shortlist: "Shortlist",
  hold: "Hold",
  auto_reject: "Auto-rejected",
};

type SortMode = "score" | "name";

export function CandidatesPage() {
  const [params] = useSearchParams();
  const requisitionId = params.get("req") ?? "";
  const [candidates, setCandidates] = useState<CandidateSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [sortMode, setSortMode] = useState<SortMode>("score");
  const [filter, setFilter] = useState("");

  useEffect(() => {
    document.title = "AIVA — Pipeline";
  }, []);

  useEffect(() => {
    if (!requisitionId) return;
    let cancelled = false;
    setCandidates(null);
    setError(null);
    listCandidates(requisitionId)
      .then((response) => {
        if (!cancelled) setCandidates(response.candidates);
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    return () => {
      cancelled = true;
    };
  }, [requisitionId]);

  const visible = useMemo(() => {
    if (!candidates) return [];
    const filtered = candidates.filter(
      (candidate) =>
        !filter ||
        candidate.filename.toLowerCase().includes(filter.toLowerCase()) ||
        (candidate.candidate_email ?? "").toLowerCase().includes(filter.toLowerCase()),
    );
    return [...filtered].sort((a, b) => {
      if (sortMode === "name") {
        return a.filename.localeCompare(b.filename);
      }
      const scoreA = a.latest_run?.total_score ?? -1;
      const scoreB = b.latest_run?.total_score ?? -1;
      if (scoreB !== scoreA) return scoreB - scoreA;
      return (VERDICT_ORDER[a.latest_run?.verdict ?? "hold"] ?? 9) - (VERDICT_ORDER[b.latest_run?.verdict ?? "hold"] ?? 9);
    });
  }, [candidates, filter, sortMode]);

  if (!requisitionId) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16 text-[var(--mist)]">
        <EmptyState
          title="Open a requisition"
          body="Append ?req=<requisition-id> to this page. Requisition browsing arrives with the full dashboard in Milestone 11."
        />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-5xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="display text-2xl font-semibold">Pipeline</h1>
          <p className="mono mt-1 text-xs text-[var(--haze)]">requisition {requisitionId}</p>
        </div>
        <div className="flex items-center gap-3">
          <Input
            aria-label="Filter candidates"
            placeholder="Filter by name or email"
            value={filter}
            onChange={(event) => setFilter(event.target.value)}
            className="w-56"
          />
          <Button
            variant="ghost"
            onClick={() => setSortMode((mode) => (mode === "score" ? "name" : "score"))}
          >
            Sort: {sortMode === "score" ? "Score" : "Name"}
          </Button>
        </div>
      </header>

      {error ? (
        <Card>
          <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>
        </Card>
      ) : null}

      {!candidates && !error ? (
        <div className="grid gap-3">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      ) : null}

      {candidates?.length === 0 ? (
        <EmptyState
          title="No candidates yet"
          body="Upload resumes against this requisition through the API; they will appear here with scores and evidence."
        />
      ) : null}

      <ul className="grid gap-3">
        {visible.map((candidate) => (
          <motion.li
            key={candidate.resume_id}
            layout
            transition={{ type: "spring", stiffness: 260, damping: 26 }}
          >
            <Card interactive className="flex flex-wrap items-center justify-between gap-4 py-4">
              <div>
                <Link
                  to={`/resumes/${candidate.resume_id}?req=${requisitionId}`}
                  className="font-medium hover:text-[var(--signal-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
                >
                  {candidate.candidate_email ?? candidate.filename}
                </Link>
                <p className="mono mt-1 text-xs text-[var(--haze)]">{candidate.filename}</p>
              </div>
              <div className="flex items-center gap-4">
                {candidate.latest_run ? (
                  <>
                    <span className="data-value text-xl font-semibold">
                      {candidate.latest_run.total_score}
                    </span>
                    <Badge tone={VERDICT_TONE[candidate.latest_run.verdict] ?? "neutral"}>
                      {VERDICT_LABEL[candidate.latest_run.verdict] ?? candidate.latest_run.verdict}
                    </Badge>
                  </>
                ) : (
                  <Badge>Not scored</Badge>
                )}
              </div>
            </Card>
          </motion.li>
        ))}
      </ul>
    </main>
  );
}
