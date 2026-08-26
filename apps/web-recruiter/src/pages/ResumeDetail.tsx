import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import {
  Badge,
  Button,
  Card,
  EvidenceSpine,
  EmptyState,
  Skeleton,
  type SpineNodeData,
} from "@aiva/ui";
import {
  downloadEvaluationExport,
  generateEvaluation,
  getLatestEvaluation,
  getResume,
  listRuns,
  type EvaluationReport,
  type ResumeDetail,
  type ScoringRunDetail,
} from "../api/client";

const DIMENSION_LABELS: Record<string, string> = {
  technical: "Technical",
  experience: "Experience",
  domain: "Domain",
  education: "Education",
  certifications: "Certifications",
  soft_skills: "Soft skills",
  stability: "Stability",
};

export function ResumeDetailPage() {
  const [params] = useSearchParams();
  const routeParams = useParams();
  const resumeId = routeParams.id ?? "";
  const [resume, setResume] = useState<ResumeDetail | null>(null);
  const [runs, setRuns] = useState<ScoringRunDetail[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [evaluation, setEvaluation] = useState<EvaluationReport | null>(null);
  const [evaluationLoaded, setEvaluationLoaded] = useState(false);

  const blind = params.get("blind") === "1";
  const requisitionId = params.get("req");

  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;
    getResume(resumeId, blind)
      .then((detail) => {
        if (!cancelled) {
          setResume(detail);
          document.title = `AIVA — ${detail.candidate_email ?? detail.filename}`;
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    listRuns(requisitionId ?? "")
      .then((response) => {
        if (!cancelled) setRuns(response.runs);
      })
      .catch(() => undefined);
    if (requisitionId) {
      getLatestEvaluation(requisitionId, resumeId)
        .then((report) => {
          if (!cancelled) {
            setEvaluation(report);
            setEvaluationLoaded(true);
          }
        })
        .catch(() => {
          if (!cancelled) setEvaluationLoaded(true);
        });
    }
    return () => {
      cancelled = true;
    };
  }, [resumeId, params]);

  // GET .../scoring-runs is already ordered newest-first, and every
  // persisted run always has non-empty checks/dimensions at creation time
  // (the list endpoint just doesn't return those two fields to stay
  // lightweight) — so the first entry is always the latest scored run.
  const latestRun = runs?.[0] ?? null;

  const spineNodes: SpineNodeData[] = useMemo(() => {
    if (!resume) return [];
    const fieldNodes: SpineNodeData[] = resume.fields
      .filter((field) => field.field_name !== "skill" || field.confidence >= 0.9)
      .slice(0, 14)
      .map((field) => ({
        id: `field:${field.start_offset}`,
        label: field.field_name.replaceAll("_", " "),
        kind: "field",
        value: field.value,
        quote: field.source_quote,
        meta: {
          page: String(field.page_number),
          offset: `${field.start_offset}–${field.end_offset}`,
          confidence: field.confidence.toFixed(2),
          extractor: field.extractor,
        },
      }));

    const dimensionNodes: SpineNodeData[] = (latestRun?.dimensions ?? []).map((dimension) => ({
      id: `dim:${dimension.dimension}`,
      label: DIMENSION_LABELS[dimension.dimension] ?? dimension.dimension,
      kind: "score",
      value: `${dimension.score}/100`,
      quote: dimension.rationale,
      meta: Object.fromEntries(
        dimension.evidence_refs.map((ref, index) => [`evidence ${index + 1}`, ref]),
      ),
    }));

    return [...dimensionNodes, ...fieldNodes];
  }, [resume, latestRun]);

  if (!resumeId) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-16">
        <EmptyState title="No resume selected" body="Open a candidate from the pipeline." />
      </main>
    );
  }

  return (
    <main className="mx-auto max-w-3xl px-6 py-10 text-[var(--mist)]">
      <div className="flex items-center justify-between">
        <Link
          to={requisitionId ? `/pipeline?req=${requisitionId}` : "/"}
          className="text-sm text-[var(--signal-text)] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
        >
          ← Back to pipeline
        </Link>
        <Link
          to={`?${new URLSearchParams({
            ...(requisitionId ? { req: requisitionId } : {}),
            ...(blind ? {} : { blind: "1" }),
          }).toString()}`}
          className="text-sm text-[var(--haze)] hover:text-[var(--signal-text)] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
        >
          {blind ? "Blind screening: on" : "Blind screening: off"}
        </Link>
      </div>

      <h1 className="display mt-4 text-2xl font-semibold">
        {resume?.candidate_email ?? resume?.filename ?? "Candidate"}
      </h1>
      {error ? (
        <Card className="mt-6">
          <p role="alert" className="text-sm text-[var(--danger)]">{error}</p>
        </Card>
      ) : null}

      {!resume && !error ? (
        <div className="mt-8 grid gap-3">
          <Skeleton className="h-8 w-1/2" />
          <Skeleton className="h-40 w-full" />
        </div>
      ) : null}

      {resume ? (
        <section aria-label="Evidence spine" className="mt-10">
          <h2 className="display mb-6 text-lg font-semibold">Evidence spine</h2>
          <EvidenceSpine nodes={spineNodes} />
        </section>
      ) : null}

      {latestRun ? (
        <Card className="mono mt-4 text-xs text-[var(--haze)]">
          run fingerprint {latestRun.run_fingerprint}
        </Card>
      ) : null}

      {resume && latestRun === null && runs !== null ? (
        <div className="mt-6">
          <Badge tone="warning">Not scored yet</Badge>
        </div>
      ) : null}

      {resume && evaluationLoaded ? (
        <EvaluationSection
          requisitionId={requisitionId ?? ""}
          resumeId={resumeId}
          evaluation={evaluation}
          onGenerated={setEvaluation}
        />
      ) : null}
    </main>
  );
}

const VERDICT_TONE: Record<string, "positive" | "accent" | "warning" | "negative"> = {
  highly_recommended: "accent",
  shortlist: "positive",
  hold: "warning",
  auto_reject: "negative",
};

function EvaluationSection({
  requisitionId,
  resumeId,
  evaluation,
  onGenerated,
}: {
  requisitionId: string;
  resumeId: string;
  evaluation: EvaluationReport | null;
  onGenerated: (report: EvaluationReport) => void;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function generate(): Promise<void> {
    setBusy(true);
    setError(null);
    try {
      onGenerated(await generateEvaluation(requisitionId, resumeId));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not generate evaluation");
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="mt-10">
      <div className="mb-4 flex items-center justify-between">
        <h2 className="display text-lg font-semibold">Evaluation</h2>
        <Button variant="ghost" disabled={busy} onClick={() => void generate()}>
          {busy ? "Generating…" : evaluation ? "Regenerate" : "Generate evaluation"}
        </Button>
      </div>
      {error && <p className="mb-3 text-sm text-[var(--danger)]">{error}</p>}
      {!evaluation ? (
        <EmptyState
          title="No evaluation yet"
          body="Generate one to aggregate resume score, questionnaire, interview, and coding-task results into a single verdict."
        />
      ) : (
        <Card>
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div className="flex items-center gap-3">
              <span className="data-value text-2xl font-semibold">
                {evaluation.overall_score}
              </span>
              <Badge tone={VERDICT_TONE[evaluation.verdict] ?? "neutral"}>
                {evaluation.verdict.replaceAll("_", " ")}
              </Badge>
            </div>
            <div className="flex gap-2">
              <Button
                variant="ghost"
                onClick={() => void downloadEvaluationExport(evaluation.id, "pdf")}
              >
                Download PDF
              </Button>
              <Button
                variant="ghost"
                onClick={() => void downloadEvaluationExport(evaluation.id, "xlsx")}
              >
                Download Excel
              </Button>
            </div>
          </div>

          <ul className="mt-4 grid gap-2">
            {evaluation.components.map((component) => (
              <li
                key={component.name}
                className="flex items-center justify-between border-t border-[var(--steel)] pt-2 text-sm"
              >
                <span className="capitalize">{component.name}</span>
                <span className="text-[var(--haze)]">{component.detail}</span>
                <span className="data-value font-semibold">{component.score}</span>
              </li>
            ))}
          </ul>

          {evaluation.narrative && (
            <p className="mt-4 leading-relaxed text-[var(--mist)]">{evaluation.narrative}</p>
          )}

          {evaluation.strengths.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haze)]">
                Strengths
              </p>
              <ul className="mt-1 list-inside list-disc text-sm">
                {evaluation.strengths.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}

          {evaluation.concerns.length > 0 && (
            <div className="mt-3">
              <p className="text-xs font-semibold uppercase tracking-wide text-[var(--haze)]">
                Concerns
              </p>
              <ul className="mt-1 list-inside list-disc text-sm">
                {evaluation.concerns.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </Card>
      )}
    </section>
  );
}
