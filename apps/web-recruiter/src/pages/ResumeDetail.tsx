import { useEffect, useMemo, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { Badge, Card, EvidenceSpine, EmptyState, Skeleton, type SpineNodeData } from "@aiva/ui";
import { getResume, listRuns, type ResumeDetail, type ScoringRunDetail } from "../api/client";

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

  useEffect(() => {
    if (!resumeId) return;
    let cancelled = false;
    getResume(resumeId)
      .then((detail) => {
        if (!cancelled) {
          setResume(detail);
          document.title = `AIVA — ${detail.candidate_email ?? detail.filename}`;
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
      });
    listRuns(params.get("req") ?? "")
      .then((response) => {
        if (!cancelled) setRuns(response.runs);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [resumeId, params]);

  const latestRun = runs?.find((run) =>
    run.checks.length > 0 || run.dimensions.length > 0,
  ) ?? null;

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
      <Link
        to={params.get("req") ? `/pipeline?req=${params.get("req")}` : "/"}
        className="text-sm text-[var(--signal-text)] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
      >
        ← Back to pipeline
      </Link>

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
    </main>
  );
}
