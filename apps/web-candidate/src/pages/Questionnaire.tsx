import { useCallback, useEffect, useRef, useState } from "react";
import { useParams } from "react-router-dom";
import { Button, Card, EmptyState, Field, Input, PageStagger, Skeleton, Textarea } from "@aiva/ui";
import {
  ApiError,
  getQuestionnaire,
  saveQuestionnaireResponse,
  type QuestionnaireQuestion,
  type QuestionnaireState,
} from "../api";

type Phase = "loading" | "ready" | "gone" | "completed" | "expired" | "submitted";

function QuestionField({
  question,
  value,
  onChange,
}: {
  question: QuestionnaireQuestion;
  value: string;
  onChange: (value: string) => void;
}) {
  if (question.type === "yes_no") {
    return (
      <div className="flex gap-3">
        {["yes", "no"].map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`min-h-11 flex-1 rounded-[var(--radius-md)] border px-4 py-2.5 text-sm font-medium capitalize transition-colors ${
              value === option
                ? "border-[var(--signal)] bg-[var(--signal-dim)] text-[var(--signal-text)]"
                : "border-[var(--steel)] text-[var(--mist)] hover:border-[var(--signal)]"
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    );
  }

  if (question.type === "rating") {
    return (
      <div className="flex gap-2">
        {[1, 2, 3, 4, 5].map((score) => (
          <button
            key={score}
            type="button"
            onClick={() => onChange(String(score))}
            aria-pressed={value === String(score)}
            className={`grid h-11 w-11 place-items-center rounded-[var(--radius-md)] border font-semibold transition-colors ${
              value === String(score)
                ? "border-[var(--signal)] bg-[var(--signal-dim)] text-[var(--signal-text)]"
                : "border-[var(--steel)] text-[var(--mist)] hover:border-[var(--signal)]"
            }`}
          >
            {score}
          </button>
        ))}
      </div>
    );
  }

  if (question.type === "multiple_choice") {
    return (
      <div className="flex flex-col gap-2">
        {(question.options ?? []).map((option) => (
          <button
            key={option}
            type="button"
            onClick={() => onChange(option)}
            className={`min-h-11 rounded-[var(--radius-md)] border px-4 py-2.5 text-left text-sm font-medium transition-colors ${
              value === option
                ? "border-[var(--signal)] bg-[var(--signal-dim)] text-[var(--signal-text)]"
                : "border-[var(--steel)] text-[var(--mist)] hover:border-[var(--signal)]"
            }`}
          >
            {option}
          </button>
        ))}
      </div>
    );
  }

  if (question.type === "long_text") {
    return (
      <Textarea
        id={question.id}
        value={value}
        onChange={(event) => onChange(event.target.value)}
        className="min-h-32"
      />
    );
  }

  return (
    <Input id={question.id} value={value} onChange={(event) => onChange(event.target.value)} />
  );
}

export default function Questionnaire() {
  const { token = "" } = useParams();
  const [phase, setPhase] = useState<Phase>("loading");
  const [state, setState] = useState<QuestionnaireState | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [missing, setMissing] = useState<string[]>([]);
  const [submitError, setSubmitError] = useState<string | null>(null);
  const [saveLabel, setSaveLabel] = useState("");
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    document.title = "AIVA — Questionnaire";
  }, []);

  useEffect(() => {
    let cancelled = false;
    getQuestionnaire(token)
      .then((data) => {
        if (cancelled) return;
        setState(data);
        setAnswers(data.answers ?? {});
        setPhase("ready");
      })
      .catch((cause: unknown) => {
        if (cancelled) return;
        if (cause instanceof ApiError && cause.status === 409) setPhase("completed");
        else if (cause instanceof ApiError && cause.status === 410) setPhase("expired");
        else setPhase("gone");
      });
    return () => {
      cancelled = true;
    };
  }, [token]);

  const autosave = useCallback(
    (next: Record<string, string>) => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
      saveTimer.current = setTimeout(() => {
        setSaveLabel("Saving…");
        saveQuestionnaireResponse(token, next, false)
          .then(() => setSaveLabel("Saved"))
          .catch(() => setSaveLabel("Save failed — will retry"));
      }, 800);
    },
    [token],
  );

  function setAnswer(id: string, value: string) {
    const next = { ...answers, [id]: value };
    setAnswers(next);
    autosave(next);
  }

  async function submit() {
    setSubmitError(null);
    try {
      const result = await saveQuestionnaireResponse(token, answers, true);
      if (!result.submitted) {
        setMissing(result.missing_required);
        setSubmitError("Please answer every required question before submitting.");
        return;
      }
      setPhase("submitted");
    } catch (cause) {
      if (cause instanceof ApiError && cause.status === 400) {
        try {
          const body = JSON.parse(cause.message) as {
            detail?: { missing_required?: string[] };
          };
          setMissing(body.detail?.missing_required ?? []);
        } catch {
          // detail wasn't the expected shape; fall through to the generic message below
        }
        setSubmitError("Please answer every required question before submitting.");
        return;
      }
      setSubmitError("Something went wrong — please try again.");
    }
  }

  if (phase === "loading") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <Skeleton className="h-64 w-full" />
      </main>
    );
  }

  if (phase === "gone") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <EmptyState
          title="Link not found"
          body="This questionnaire link is invalid. Double-check the link from your recruiter."
        />
      </main>
    );
  }

  if (phase === "expired") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <EmptyState
          title="Link expired"
          body="This questionnaire invitation has expired. Contact your recruiter for a new link."
        />
      </main>
    );
  }

  if (phase === "completed") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <EmptyState
          title="Already submitted"
          body="You have already completed this questionnaire. Your recruiter has been notified."
        />
      </main>
    );
  }

  if (phase === "submitted") {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <EmptyState
          title="Thank you"
          body="Your responses have been submitted. Your recruiter will be in touch about next steps."
        />
      </main>
    );
  }

  if (!state) return null;

  return (
    <main className="mx-auto max-w-2xl px-6 py-12">
      <PageStagger>
        <div>
          <h1 className="display text-2xl font-bold">{state.title}</h1>
          <p className="mt-2 text-sm text-[var(--haze)]">
            Your answers save automatically as you go. {saveLabel}
          </p>
        </div>

        <div className="flex flex-col gap-5">
          {state.questions.map((question) => (
            <Card key={question.id}>
              <Field
                label={question.prompt + (question.required ? " *" : "")}
                htmlFor={question.id}
                error={missing.includes(question.id) ? "This question is required." : undefined}
              >
                <QuestionField
                  question={question}
                  value={answers[question.id] ?? ""}
                  onChange={(value) => setAnswer(question.id, value)}
                />
              </Field>
            </Card>
          ))}
        </div>

        {submitError ? (
          <p role="alert" className="text-sm text-[var(--danger)]">
            {submitError}
          </p>
        ) : null}
        <Button
          onClick={() => {
            void submit();
          }}
          arrow
        >
          Submit
        </Button>
      </PageStagger>
    </main>
  );
}
