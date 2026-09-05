import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, Field, Input, Skeleton, Textarea } from "@aiva/ui";
import {
  createJobDescription,
  getJobDescription,
  getRequisition,
  type JobDescriptionDetail,
  type RequisitionDetail as RequisitionDetailType,
} from "../api/client";

function parseSkillList(value: string): string[] {
  return value
    .split(",")
    .map((skill) => skill.trim())
    .filter(Boolean);
}

export function RequisitionDetailPage() {
  const { id: requisitionId } = useParams();
  const [requisition, setRequisition] = useState<RequisitionDetailType | null>(null);
  const [jd, setJd] = useState<JobDescriptionDetail | null | undefined>(undefined);
  const [error, setError] = useState<string | null>(null);

  const [showJdForm, setShowJdForm] = useState(false);
  const [jdTitle, setJdTitle] = useState("");
  const [jdRawText, setJdRawText] = useState("");
  const [jdRequired, setJdRequired] = useState("");
  const [jdPreferred, setJdPreferred] = useState("");
  const [jdMinYears, setJdMinYears] = useState(0);
  const [jdBusy, setJdBusy] = useState(false);

  useEffect(() => {
    document.title = "AIVA — Requisition";
  }, []);

  async function refresh(rid: string) {
    const [req, jobDescription] = await Promise.all([
      getRequisition(rid),
      getJobDescription(rid),
    ]);
    setRequisition(req);
    setJd(jobDescription);
  }

  useEffect(() => {
    if (!requisitionId) return;
    let cancelled = false;
    refresh(requisitionId).catch((cause: unknown) => {
      if (!cancelled) setError(cause instanceof Error ? cause.message : "Failed to load");
    });
    return () => {
      cancelled = true;
    };
  }, [requisitionId]);

  async function submitJd(event: React.FormEvent) {
    event.preventDefault();
    if (!requisitionId) return;
    setJdBusy(true);
    setError(null);
    try {
      await createJobDescription(requisitionId, {
        title: jdTitle,
        raw_text: jdRawText,
        required_skills: parseSkillList(jdRequired),
        preferred_skills: parseSkillList(jdPreferred),
        min_years_experience: jdMinYears,
      });
      setShowJdForm(false);
      setJdTitle("");
      setJdRawText("");
      setJdRequired("");
      setJdPreferred("");
      setJdMinYears(0);
      await refresh(requisitionId);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to save job description");
    } finally {
      setJdBusy(false);
    }
  }

  if (!requisitionId) return null;

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 text-[var(--mist)]">
      {!requisition && !error ? <Skeleton className="h-24 w-full" /> : null}

      {error ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      {requisition ? (
        <>
          <header className="mb-8 flex flex-wrap items-center justify-between gap-4">
            <div>
              <Link
                to="/requisitions"
                className="text-xs text-[var(--haze)] hover:text-[var(--signal-text)]"
              >
                ← Requisitions
              </Link>
              <h1 className="display mt-1 text-2xl font-semibold">{requisition.title}</h1>
            </div>
            <Badge tone={requisition.status === "open" ? "positive" : "neutral"}>
              {requisition.status}
            </Badge>
          </header>

          <div className="mb-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <NavCard to={`/requisitions/${requisitionId}/upload`} label="Upload resumes" />
            <NavCard to={`/pipeline?req=${requisitionId}`} label="Pipeline" />
            <NavCard to={`/requisitions/${requisitionId}/questionnaire`} label="Questionnaire" />
            <NavCard to={`/requisitions/${requisitionId}/scheduling`} label="Scheduling" />
            <NavCard to={`/sessions?req=${requisitionId}`} label="Interview sessions" />
          </div>

          <Card>
            <div className="mb-4 flex items-center justify-between">
              <h2 className="display text-lg font-semibold">Job description</h2>
              {jd ? (
                <Button variant="ghost" onClick={() => setShowJdForm((show) => !show)}>
                  {showJdForm ? "Cancel" : "New version"}
                </Button>
              ) : null}
            </div>

            {jd === undefined ? <Skeleton className="h-32 w-full" /> : null}

            {jd && !showJdForm ? (
              <div className="flex flex-col gap-4">
                <div>
                  <p className="font-medium">{jd.title}</p>
                  <p className="mt-2 whitespace-pre-wrap text-sm text-[var(--haze)]">
                    {jd.raw_text}
                  </p>
                </div>
                <div className="flex flex-wrap gap-2">
                  {jd.required_skills.map((skill) => (
                    <Badge key={skill} tone="accent">
                      {skill}
                    </Badge>
                  ))}
                  {jd.preferred_skills.map((skill) => (
                    <Badge key={skill} tone="neutral">
                      {skill}
                    </Badge>
                  ))}
                </div>
                <p className="text-xs text-[var(--haze)]">
                  Minimum experience: {jd.min_years_experience} years
                </p>
              </div>
            ) : null}

            {jd === null || showJdForm ? (
              <form
                onSubmit={(event) => {
                  void submitJd(event);
                }}
                className="flex flex-col gap-4"
              >
                <Field label="Title" htmlFor="jd-title">
                  <Input
                    id="jd-title"
                    value={jdTitle}
                    onChange={(event) => setJdTitle(event.target.value)}
                    required
                  />
                </Field>
                <Field
                  label="Description"
                  htmlFor="jd-raw"
                  hint="Paste the full job description text."
                >
                  <Textarea
                    id="jd-raw"
                    value={jdRawText}
                    onChange={(event) => setJdRawText(event.target.value)}
                    required
                    className="min-h-40"
                  />
                </Field>
                <div className="grid gap-4 sm:grid-cols-2">
                  <Field
                    label="Required skills"
                    htmlFor="jd-required"
                    hint="Comma-separated"
                  >
                    <Input
                      id="jd-required"
                      value={jdRequired}
                      onChange={(event) => setJdRequired(event.target.value)}
                      placeholder="python, postgresql, aws"
                    />
                  </Field>
                  <Field
                    label="Preferred skills"
                    htmlFor="jd-preferred"
                    hint="Comma-separated"
                  >
                    <Input
                      id="jd-preferred"
                      value={jdPreferred}
                      onChange={(event) => setJdPreferred(event.target.value)}
                      placeholder="kubernetes, terraform"
                    />
                  </Field>
                </div>
                <Field label="Minimum years experience" htmlFor="jd-years">
                  <Input
                    id="jd-years"
                    type="number"
                    min={0}
                    max={50}
                    value={jdMinYears}
                    onChange={(event) => setJdMinYears(Number(event.target.value))}
                  />
                </Field>
                <Button type="submit" disabled={jdBusy} arrow className="self-start">
                  {jdBusy ? "Saving…" : "Save job description"}
                </Button>
              </form>
            ) : null}
          </Card>
        </>
      ) : null}
    </main>
  );
}

function NavCard({ to, label }: { to: string; label: string }) {
  return (
    <Link to={to}>
      <Card
        interactive
        className="flex h-full items-center justify-between py-4 text-sm font-medium"
      >
        {label}
        <span aria-hidden="true" className="text-[var(--haze)]">
          →
        </span>
      </Card>
    </Link>
  );
}
