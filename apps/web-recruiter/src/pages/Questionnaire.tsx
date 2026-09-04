import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, Field, Input, Skeleton } from "@aiva/ui";
import {
  createQuestionnaire,
  createQuestionnaireInvite,
  listQuestionnaireResponses,
  listQuestionnaires,
  type QuestionnaireQuestion,
  type QuestionnaireResponseSummary,
  type QuestionnaireSummary,
} from "../api/client";

const QUICK_START_TEMPLATE: QuestionnaireQuestion[] = [
  { id: "notice_period", prompt: "What is your current notice period?", type: "short_text", required: true },
  { id: "current_salary", prompt: "What is your current salary?", type: "short_text", required: true },
  { id: "expected_salary", prompt: "What is your expected salary?", type: "short_text", required: true },
  {
    id: "work_authorization",
    prompt: "Are you authorized to work in this location without sponsorship?",
    type: "yes_no",
    required: true,
  },
  { id: "relocate", prompt: "Are you willing to relocate for this role?", type: "yes_no", required: true },
  {
    id: "remote_preference",
    prompt: "What is your work-location preference?",
    type: "multiple_choice",
    required: true,
    options: ["Remote", "Hybrid", "On-site"],
  },
  {
    id: "technical_self_assessment",
    prompt: "Rate your overall technical proficiency for this role (1-5).",
    type: "rating",
    required: true,
  },
  { id: "certifications", prompt: "List any relevant certifications.", type: "long_text" },
  {
    id: "portfolio_links",
    prompt: "Share links to your GitHub, LinkedIn, or portfolio.",
    type: "short_text",
  },
  { id: "availability", prompt: "When are you available to start?", type: "short_text", required: true },
  {
    id: "preferred_interview_times",
    prompt: "What times work best for an interview over the next two weeks?",
    type: "long_text",
  },
];

export function QuestionnairePage() {
  const { id: requisitionId } = useParams();
  const [questionnaires, setQuestionnaires] = useState<QuestionnaireSummary[] | null>(null);
  const [responses, setResponses] = useState<QuestionnaireResponseSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creating, setCreating] = useState(false);

  const [inviteFor, setInviteFor] = useState<string | null>(null);
  const [inviteEmail, setInviteEmail] = useState("");
  const [inviteBusy, setInviteBusy] = useState(false);
  const [lastInviteLink, setLastInviteLink] = useState<string | null>(null);

  useEffect(() => {
    document.title = "AIVA — Questionnaire";
  }, []);

  async function refresh(rid: string) {
    const [q, r] = await Promise.all([listQuestionnaires(rid), listQuestionnaireResponses(rid)]);
    setQuestionnaires(q.questionnaires);
    setResponses(r.responses);
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

  if (!requisitionId) return null;

  async function createFromTemplate() {
    setCreating(true);
    setError(null);
    try {
      await createQuestionnaire(requisitionId!, "Candidate Questionnaire", QUICK_START_TEMPLATE);
      await refresh(requisitionId!);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to create questionnaire");
    } finally {
      setCreating(false);
    }
  }

  async function sendInvite(questionnaireId: string) {
    if (!inviteEmail.trim()) return;
    setInviteBusy(true);
    setError(null);
    try {
      const invite = await createQuestionnaireInvite(questionnaireId, inviteEmail.trim());
      const link = `${window.location.origin.replace(/:\d+$/, ":15174")}/questionnaire/${invite.token}`;
      setLastInviteLink(link);
      setInviteEmail("");
      setInviteFor(null);
      await refresh(requisitionId!);
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Failed to send invite");
    } finally {
      setInviteBusy(false);
    }
  }

  return (
    <main className="mx-auto max-w-4xl px-6 py-10 text-[var(--mist)]">
      <header className="mb-8">
        <Link
          to={`/requisitions/${requisitionId}`}
          className="text-xs text-[var(--haze)] hover:text-[var(--signal-text)]"
        >
          ← Requisition
        </Link>
        <h1 className="display mt-1 text-2xl font-semibold">Questionnaire</h1>
      </header>

      {error ? (
        <Card className="mb-6">
          <p role="alert" className="text-sm text-[var(--danger)]">
            {error}
          </p>
        </Card>
      ) : null}

      {lastInviteLink ? (
        <Card className="mb-6 border-[var(--signal)]">
          <p className="text-sm font-medium">Invite link (shown once — copy it now):</p>
          <p className="mono mt-2 break-all text-xs text-[var(--signal-text)]">{lastInviteLink}</p>
        </Card>
      ) : null}

      {!questionnaires && !error ? <Skeleton className="h-24 w-full" /> : null}

      {questionnaires?.length === 0 ? (
        <EmptyState
          title="No questionnaire yet"
          body="Start from a quick-start template covering notice period, salary expectations, work authorization, and more — you can invite candidates immediately."
          action={
            <Button
              onClick={() => {
                void createFromTemplate();
              }}
              disabled={creating}
              arrow
            >
              {creating ? "Creating…" : "Create from template"}
            </Button>
          }
        />
      ) : null}

      <ul className="mb-8 grid gap-3">
        {questionnaires?.map((q) => (
          <Card key={q.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">{q.title}</p>
                <p className="mono mt-1 text-xs text-[var(--haze)]">{q.question_count} questions</p>
              </div>
              <Button variant="ghost" onClick={() => setInviteFor(inviteFor === q.id ? null : q.id)}>
                {inviteFor === q.id ? "Cancel" : "Invite candidate"}
              </Button>
            </div>
            {inviteFor === q.id ? (
              <form
                onSubmit={(event) => {
                  event.preventDefault();
                  void sendInvite(q.id);
                }}
                className="mt-4 flex flex-wrap items-end gap-3"
              >
                <div className="min-w-64 flex-1">
                  <Field label="Candidate email" htmlFor={`invite-${q.id}`}>
                    <Input
                      id={`invite-${q.id}`}
                      type="email"
                      required
                      value={inviteEmail}
                      onChange={(event) => setInviteEmail(event.target.value)}
                    />
                  </Field>
                </div>
                <Button type="submit" disabled={inviteBusy}>
                  {inviteBusy ? "Sending…" : "Send invite"}
                </Button>
              </form>
            ) : null}
          </Card>
        ))}
      </ul>

      <h2 className="display mb-4 text-lg font-semibold">Responses</h2>
      {responses?.length === 0 ? (
        <EmptyState title="No responses yet" body="Responses appear here as candidates submit." />
      ) : null}
      <ul className="grid gap-3">
        {responses?.map((response) => (
          <Card key={response.id}>
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div>
                <p className="font-medium">{response.candidate_email ?? "Unknown candidate"}</p>
                <p className="mono mt-1 text-xs text-[var(--haze)]">
                  {response.history_entries} save{response.history_entries === 1 ? "" : "s"}
                  {response.submitted_at ? ` · submitted ${response.submitted_at.slice(0, 10)}` : ""}
                </p>
              </div>
              <Badge tone={response.submitted ? "positive" : "neutral"}>
                {response.submitted ? "Submitted" : "In progress"}
              </Badge>
            </div>
            {response.missing_required.length > 0 ? (
              <p className="mt-2 text-xs text-[var(--warning)]">
                Missing: {response.missing_required.join(", ")}
              </p>
            ) : null}
          </Card>
        ))}
      </ul>
    </main>
  );
}
