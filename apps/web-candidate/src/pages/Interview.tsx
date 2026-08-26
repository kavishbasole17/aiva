import { Badge, Button, Card, EmptyState } from "@aiva/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  ApiError,
  finishInterview,
  getSessionState,
  reportIntegritySignal,
  speak,
  startInterview,
  submitConsent,
  submitPrecheck,
  submitTurnAnswer,
  submitTurnAudio,
} from "../api";
import type { PreCheckReport, Question, SessionState } from "../api";
import { base64ToBlobUrl, blobToBase64 } from "../audio";
import PreCheckGate from "./PreCheck";
import { WorkspacePanel } from "./Workspace";

interface TranscriptEntry {
  questionText: string;
  answerText: string | null;
  viaAudio: boolean;
}

interface LocationState {
  token?: string;
}

export default function Interview() {
  const location = useLocation();
  const navigate = useNavigate();
  const [token] = useState<string>(
    () => (location.state as LocationState | null)?.token ?? "",
  );
  const [state, setState] = useState<SessionState | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!token) {
      navigate("/", { replace: true });
      return;
    }
    let cancelled = false;
    getSessionState(token)
      .then((snapshot) => {
        if (!cancelled) setState(snapshot);
      })
      .catch((exception: unknown) => {
        if (!cancelled) {
          setError(exception instanceof ApiError ? `Link rejected (${exception.status})` : "Network error");
        }
      });
    return () => {
      cancelled = true;
    };
  }, [token, navigate]);

  if (!token) return null;

  if (error) {
    return (
      <main className="mx-auto flex max-w-2xl flex-col gap-8 px-6 py-12">
        <EmptyState title="Cannot open interview" body={error} />
        <div className="flex justify-center">
          <Button variant="ghost" onClick={() => navigate("/")}>
            Back to link entry
          </Button>
        </div>
      </main>
    );
  }
  if (!state) {
    return (
      <main className="mx-auto max-w-2xl px-6 py-12">
        <Card>
          <p className="animate-pulse text-[var(--haze)]">Opening your session…</p>
        </Card>
      </main>
    );
  }

  switch (state.status) {
    case "pending_consent":
      return <ConsentGate state={state} token={token} onDone={setState} />;
    case "consent_granted":
    case "precheck_passed":
      return <PrecheckFlow state={state} token={token} onDone={setState} />;
    case "active":
      return <Hud state={state} token={token} onDone={setState} />;
    case "completed":
      return (
        <CenteredCard>
          <EmptyState
            title="Interview complete"
            body="Thank you — your answers are saved and the hiring team will take it from here. You can close this window."
          />
        </CenteredCard>
      );
    case "declined":
      return (
        <CenteredCard>
          <EmptyState
            title="Consent declined"
            body="The interview was not started and nothing was recorded. Contact your recruiter if you change your mind."
          />
        </CenteredCard>
      );
    case "aborted":
      return (
        <CenteredCard>
          <EmptyState
            title="Session ended"
            body="You ended this interview early. Your recruiter has been notified through the audit trail."
          />
        </CenteredCard>
      );
    default:
      return null;
  }
}

function CenteredCard({ children }: { children: React.ReactNode }) {
  return (
    <main className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-12">{children}</main>
  );
}

function ConsentGate({
  state,
  token,
  onDone,
}: {
  state: SessionState;
  token: string;
  onDone: (next: SessionState) => void;
}) {
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function decide(granted: boolean): Promise<void> {
    setBusy(true);
    try {
      await submitConsent(token, state.consent.version, granted);
      onDone(await getSessionState(token));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not record consent");
    } finally {
      setBusy(false);
    }
  }

  return (
    <CenteredCard>
      <Card>
        <p className="text-sm uppercase tracking-widest text-[var(--haze)]">Step 3 of 3</p>
        <h1 className="display mt-2 text-2xl font-bold">Recording consent</h1>
        <p className="mt-4 rounded-lg border border-[var(--steel)] bg-[var(--abyss)] p-4 leading-relaxed">
          {state.consent.statement}
        </p>
        <p className="mt-3 text-sm text-[var(--haze)]">
          Consent statement version {state.consent.version} — declining ends the session here.
        </p>
        {error && (
          <p role="alert" className="mt-4 text-sm text-[var(--danger, #e5484d)]">
            {error}
          </p>
        )}
        <div className="mt-6 flex justify-between">
          <Button variant="danger" disabled={busy} onClick={() => void decide(false)}>
            Decline
          </Button>
          <Button disabled={busy} onClick={() => void decide(true)}>
            I consent — continue to equipment check
          </Button>
        </div>
      </Card>
    </CenteredCard>
  );
}

function PrecheckFlow({
  state,
  token,
  onDone,
}: {
  state: SessionState;
  token: string;
  onDone: (next: SessionState) => void;
}) {
  const handleReport = useCallback(
    async (report: PreCheckReport) => {
      try {
        const result = await submitPrecheck(token, report);
        if (!result.passed) {
          window.alert(`Check failed:\n${result.failures.join("\n")}`);
        }
        onDone(await getSessionState(token));
      } catch (exception) {
        window.alert(exception instanceof Error ? exception.message : "Submission failed");
      }
    },
    [token, onDone],
  );

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-6 px-6 py-12">
      <PreCheckGate
        suiteVersion={state.precheck.suite_version}
        onPassed={(report) => handleReport(report)}
      />
    </main>
  );
}

function Hud({
  state,
  token,
  onDone,
}: {
  state: SessionState;
  token: string;
  onDone: (next: SessionState) => void;
}) {
  const [question, setQuestion] = useState<Question | null>(() =>
    state.open_question
      ? {
          kind: state.open_question.kind,
          topic_id: state.open_question.topic_id,
          text: state.open_question.text,
          tts_text: state.open_question.text,
        }
      : null,
  );
  const [progressTotal, setProgressTotal] = useState<number>(0);
  const [transcript, setTranscript] = useState<TranscriptEntry[]>([]);
  const [answer, setAnswer] = useState("");
  const [busy, setBusy] = useState(false);
  const [recording, setRecording] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [elapsed, setElapsed] = useState(0);
  const [view, setView] = useState<"interview" | "workspace">("interview");
  const recorderRef = useRef<MediaRecorder | null>(null);
  const chunksRef = useRef<Blob[]>([]);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  useEffect(() => {
    const timer = setInterval(() => setElapsed((seconds) => seconds + 1), 1000);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => () => recorderRef.current?.stream.getTracks().forEach((t) => t.stop()), []);

  // Real signal, zero ML dependency: the browser already knows when the
  // candidate leaves the tab. Face/gaze-based proctoring stays deferred to
  // GPU deployment (ADR-023) — this doesn't try to approximate it.
  useEffect(() => {
    function onBlur(): void {
      void reportIntegritySignal(token, "tab_blur");
    }
    function onFocus(): void {
      void reportIntegritySignal(token, "tab_focus");
    }
    function onVisibility(): void {
      void reportIntegritySignal(token, document.hidden ? "visibility_hidden" : "visibility_visible");
    }
    window.addEventListener("blur", onBlur);
    window.addEventListener("focus", onFocus);
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      window.removeEventListener("blur", onBlur);
      window.removeEventListener("focus", onFocus);
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [token]);

  async function begin(): Promise<void> {
    setBusy(true);
    try {
      const result = await startInterview(token);
      setQuestion(result.question);
      setProgressTotal(result.progress_total);
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not start");
    } finally {
      setBusy(false);
    }
  }

  async function playTts(text: string): Promise<void> {
    try {
      const synthesis = await speak(token, text);
      const url = base64ToBlobUrl(synthesis.audio_b64, `audio/${synthesis.format}`);
      if (audioRef.current) {
        audioRef.current.src = url;
        await audioRef.current.play().catch(() => undefined);
      }
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Speech playback failed");
    }
  }

  function startRecording(): void {
    setError(null);
    navigator.mediaDevices
      .getUserMedia({ audio: true })
      .then((stream) => {
        chunksRef.current = [];
        const recorder = new MediaRecorder(stream);
        recorder.ondataavailable = (event) => {
          if (event.data.size > 0) chunksRef.current.push(event.data);
        };
        recorder.onstop = () => {
          stream.getTracks().forEach((track) => track.stop());
          void sendRecording();
        };
        recorderRef.current = recorder;
        recorder.start();
        setRecording(true);
      })
      .catch(() => setError("Microphone access denied; type your answer instead."));
  }

  function stopRecording(): void {
    setRecording(false);
    recorderRef.current?.stop();
  }

  async function sendRecording(): Promise<void> {
    const blobParts = chunksRef.current;
    if (blobParts.length === 0) {
      setError("Recording was empty.");
      return;
    }
    setBusy(true);
    try {
      const audioB64 = await blobToBase64(new Blob(blobParts));
      const result = await submitTurnAudio(token, audioB64);
      applyTurn(result, "(spoken answer)");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not send recording");
    } finally {
      setBusy(false);
    }
  }

  function applyTurn(result: Awaited<ReturnType<typeof submitTurnAnswer>>, rawAnswer: string): void {
    setTranscript((entries) => [
      ...entries,
      {
        questionText: question?.text ?? "",
        answerText: rawAnswer,
        viaAudio: Boolean(result.stt),
      },
    ]);
    if (result.completed || result.next.kind === "closing") {
      getSessionState(token)
        .then(onDone)
        .catch(() => undefined);
      setQuestion(null);
      return;
    }
    setAnswer("");
    setQuestion(result.next);
  }

  async function sendText(): Promise<void> {
    if (!question || !answer.trim()) return;
    setBusy(true);
    setError(null);
    try {
      const result = await submitTurnAnswer(token, answer.trim());
      applyTurn(result, answer.trim());
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not send answer");
    } finally {
      setBusy(false);
    }
  }

  async function endEarly(): Promise<void> {
    setBusy(true);
    try {
      await finishInterview(token);
      onDone(await getSessionState(token));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not end session");
    } finally {
      setBusy(false);
    }
  }

  const asked = state.progress.asked_turns;
  const minutes = String(Math.floor(elapsed / 60)).padStart(2, "0");
  const seconds = String(elapsed % 60).padStart(2, "0");

  return (
    <main className="mx-auto flex min-h-screen max-w-3xl flex-col gap-6 px-6 py-10 pb-32">
      <audio ref={audioRef} hidden />

      <header className="flex items-center justify-between border-b border-[var(--steel)] pb-4">
        <div className="flex items-center gap-3">
          <Badge tone="positive">Live</Badge>
          <span className="font-mono text-lg" aria-label="elapsed time">
            {minutes}:{seconds}
          </span>
        </div>
        <div className="flex items-center gap-2 font-mono text-sm text-[var(--haze)]">
          <span>
            topics {Math.min(asked + 1, progressTotal || asked + 1)}
            {progressTotal > 0 ? `/${progressTotal}` : ""}
          </span>
          <span
            className="flex h-2 w-2 rounded-full bg-[var(--positive, #30a46c)]"
            aria-hidden="true"
          />
        </div>
      </header>

      <ol className="flex items-center gap-2" aria-label="topic progress">
        {Array.from({ length: Math.max(progressTotal, asked + 1, 1) }).map((_, index) => (
          <li
            key={index}
            className={`h-1.5 flex-1 rounded-full ${
              index <= asked ? "bg-[var(--signal)]" : "bg-[var(--steel)]"
            }`}
          />
        ))}
      </ol>

      <div className="flex gap-2 border-b border-[var(--steel)] pb-2">
        {(["interview", "workspace"] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => setView(candidate)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
              view === candidate
                ? "bg-[var(--signal)] text-white"
                : "text-[var(--haze)] hover:text-[var(--mist)]"
            }`}
          >
            {candidate}
          </button>
        ))}
      </div>

      {view === "workspace" && <WorkspacePanel token={token} />}

      {view === "interview" &&
        (question ? (
          <>
            <Card interactive={false}>
              <div className="flex items-start justify-between gap-4">
                <div>
                  <Badge tone={question.kind === "probe" ? "warning" : "accent"}>
                    {question.kind === "probe" ? "Follow-up" : "Question"}
                  </Badge>
                  <p className="mt-3 whitespace-pre-line text-lg leading-relaxed">
                    {question.text}
                  </p>
                </div>
                <Button variant="ghost" onClick={() => void playTts(question.tts_text)}>
                  Read aloud
                </Button>
              </div>
            </Card>

            <Card interactive={false}>
              <textarea
                value={answer}
                onChange={(event) => setAnswer(event.target.value)}
                rows={4}
                placeholder="Type your answer, or record it instead…"
                className="w-full resize-y rounded-md border border-[var(--steel)] bg-[var(--abyss)] p-3 leading-relaxed outline-none focus:border-[var(--signal)]"
              />
              {error && (
                <p role="alert" className="mt-2 text-sm text-[var(--danger, #e5484d)]">
                  {error}
                </p>
              )}
              <div className="mt-4 flex items-center justify-between">
                <Button
                  variant={recording ? "danger" : "action"}
                  onClick={recording ? stopRecording : startRecording}
                >
                  {recording ? "Stop & send recording" : "Record answer"}
                </Button>
                <Button disabled={busy || !answer.trim()} onClick={() => void sendText()}>
                  Send answer
                </Button>
              </div>
            </Card>

            <details className="rounded-lg border border-[var(--steel)] p-4 text-sm">
              <summary className="cursor-pointer text-[var(--haze)]">
                Your answers so far ({transcript.length})
              </summary>
              <ul className="mt-3 flex flex-col gap-2">
                {transcript.map((entry, index) => (
                  <li key={index} className="flex gap-2">
                    <span className="font-mono text-[var(--haze)]">{index + 1}.</span>
                    <span>
                      {entry.answerText}{" "}
                      {entry.viaAudio && <em className="text-[var(--haze)]">(transcribed)</em>}
                    </span>
                  </li>
                ))}
              </ul>
            </details>
          </>
        ) : (
          <Card>
            <p className="leading-relaxed">
              Everything is ready. When you press start, the interviewer asks its first question.
            </p>
            <div className="mt-4">
              <Button disabled={busy} onClick={() => void begin()}>
                Start interview
              </Button>
            </div>
          </Card>
        ))}

      <footer className="fixed inset-x-0 bottom-0 border-t border-[var(--steel)] bg-[var(--hull)] px-6 py-3 backdrop-blur">
        <div className="mx-auto flex max-w-3xl items-center justify-between">
          <span className="text-sm text-[var(--haze)]">{state.candidate_email}</span>
          {question && (
            <Button variant="danger" disabled={busy} onClick={() => void endEarly()}>
              End interview
            </Button>
          )}
        </div>
      </footer>
    </main>
  );
}
