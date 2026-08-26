import { useCallback, useEffect, useRef, useState } from "react";
import type { PointerEvent } from "react";
import { Link, useParams } from "react-router-dom";
import { Badge, Button, Card, EmptyState, Field, Input, Skeleton } from "@aiva/ui";
import {
  addStroke,
  createTask,
  getCode,
  getIntegritySignals,
  getInterviewSession,
  listDiscussion,
  listExecutions,
  listTasks,
  listWhiteboard,
  postDiscussion,
  type CodeExecutionDetail,
  type CodingTask,
  type DiscussionMessage,
  type InterviewSessionDetail as SessionDetail,
  type StrokePayload,
  type WhiteboardStroke,
} from "../api/client";

const LANGUAGES = ["python", "javascript"] as const;

export function InterviewSessionDetailPage() {
  const { id } = useParams();
  const sessionId = id ?? "";
  const [session, setSession] = useState<SessionDetail | null>(null);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(() => {
    if (!sessionId) return;
    getInterviewSession(sessionId)
      .then(setSession)
      .catch((cause: unknown) => setError(cause instanceof Error ? cause.message : "Failed to load"));
  }, [sessionId]);

  useEffect(() => {
    document.title = "AIVA — Interview session";
  }, []);

  useEffect(() => {
    reload();
  }, [reload]);

  if (!sessionId) return null;

  if (error) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-16 text-[var(--mist)]">
        <EmptyState title="Cannot open session" body={error} />
      </main>
    );
  }

  if (!session) {
    return (
      <main className="mx-auto max-w-3xl px-6 py-10">
        <Skeleton className="h-8 w-1/2" />
        <Skeleton className="mt-4 h-40 w-full" />
      </main>
    );
  }

  return (
    <main className="mx-auto flex max-w-3xl flex-col gap-8 px-6 py-10 text-[var(--mist)]">
      <div>
        <Link
          to="/pipeline"
          className="text-sm text-[var(--signal-text)] hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-[var(--signal)]"
        >
          ← Back to pipeline
        </Link>
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3">
          <h1 className="display text-2xl font-semibold">{session.candidate_email}</h1>
          <Badge tone={session.status === "active" ? "accent" : "neutral"}>
            {session.status.replaceAll("_", " ")}
          </Badge>
        </div>
      </div>

      <TranscriptSection session={session} />
      <IntegritySection sessionId={sessionId} />
      <WorkspaceSection sessionId={sessionId} />
    </main>
  );
}

function TranscriptSection({ session }: { session: SessionDetail }) {
  if (session.turns.length === 0) {
    return (
      <EmptyState
        title="No transcript yet"
        body="Turns appear here once the candidate starts the interview."
      />
    );
  }
  return (
    <section>
      <h2 className="display mb-4 text-lg font-semibold">Transcript</h2>
      <ol className="flex flex-col gap-3">
        {session.turns.map((turn) => (
          <li key={turn.sequence}>
            <Card>
              <Badge tone={turn.kind === "probe" ? "warning" : "accent"}>{turn.kind}</Badge>
              <p className="mt-2 leading-relaxed">{turn.question_text}</p>
              {turn.answer_text && (
                <p className="mt-2 border-l-2 border-[var(--steel)] pl-3 text-[var(--haze)]">
                  {turn.answer_text}
                </p>
              )}
            </Card>
          </li>
        ))}
      </ol>
    </section>
  );
}

function IntegritySection({ sessionId }: { sessionId: string }) {
  const [summary, setSummary] = useState<Record<string, number> | null>(null);

  useEffect(() => {
    let cancelled = false;
    getIntegritySignals(sessionId)
      .then((res) => {
        if (!cancelled) setSummary(res.summary);
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [sessionId]);

  const entries = Object.entries(summary ?? {});
  const tabAway = (summary?.tab_blur ?? 0) + (summary?.visibility_hidden ?? 0);

  return (
    <Card>
      <p className="text-sm font-semibold">Integrity signals</p>
      <p className="mt-1 text-xs text-[var(--haze)]">
        Browser-reported tab focus/visibility events only — no face or gaze
        analysis (that needs GPU model deployment, not wired up here).
      </p>
      {entries.length === 0 ? (
        <p className="mt-3 text-sm text-[var(--haze)]">No signals reported.</p>
      ) : (
        <p className="mt-3 text-sm">
          {tabAway > 0 ? (
            <Badge tone="warning">left the tab {tabAway}×</Badge>
          ) : (
            <Badge tone="positive">stayed on tab</Badge>
          )}
        </p>
      )}
    </Card>
  );
}

function WorkspaceSection({ sessionId }: { sessionId: string }) {
  const [tasks, setTasks] = useState<CodingTask[] | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [showForm, setShowForm] = useState(false);

  const reloadTasks = useCallback(() => {
    listTasks(sessionId)
      .then((res) => {
        setTasks(res.tasks);
        setActiveTaskId((current) => current ?? res.tasks[0]?.id ?? null);
      })
      .catch(() => undefined);
  }, [sessionId]);

  useEffect(() => {
    reloadTasks();
    const interval = setInterval(reloadTasks, 5000);
    return () => clearInterval(interval);
  }, [reloadTasks]);

  const activeTask = tasks?.find((task) => task.id === activeTaskId) ?? null;

  return (
    <section className="flex flex-col gap-4">
      <div className="flex items-center justify-between">
        <h2 className="display text-lg font-semibold">Live workspace</h2>
        <Button variant="ghost" onClick={() => setShowForm((current) => !current)}>
          {showForm ? "Cancel" : "New coding task"}
        </Button>
      </div>

      {showForm && (
        <TaskForm
          sessionId={sessionId}
          onCreated={() => {
            setShowForm(false);
            reloadTasks();
          }}
        />
      )}

      {tasks && tasks.length > 1 && (
        <div className="flex flex-wrap gap-2">
          {tasks.map((task) => (
            <Button
              key={task.id}
              variant={task.id === activeTask?.id ? "primary" : "ghost"}
              onClick={() => setActiveTaskId(task.id)}
            >
              {task.title}
            </Button>
          ))}
        </div>
      )}

      {activeTask && <TaskWatcher sessionId={sessionId} task={activeTask} />}

      <WhiteboardViewer sessionId={sessionId} />
      <DiscussionThread sessionId={sessionId} />

      <Card>
        <p className="text-sm text-[var(--haze)]">
          Screen share requires WebRTC/LiveKit infrastructure not wired into this deployment yet
          — the candidate-side call returns a clear 501 rather than pretending to work.
        </p>
      </Card>
    </section>
  );
}

function TaskForm({ sessionId, onCreated }: { sessionId: string; onCreated: () => void }) {
  const [title, setTitle] = useState("");
  const [prompt, setPrompt] = useState("");
  const [starterCode, setStarterCode] = useState("");
  const [language, setLanguage] = useState<(typeof LANGUAGES)[number]>("python");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(): Promise<void> {
    if (!title.trim() || !prompt.trim()) return;
    setBusy(true);
    setError(null);
    try {
      await createTask(sessionId, {
        title: title.trim(),
        prompt: prompt.trim(),
        starter_code: starterCode,
        language,
      });
      onCreated();
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not create task");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <div className="flex flex-col gap-3">
        <Field label="Title" htmlFor="task-title">
          <Input id="task-title" value={title} onChange={(event) => setTitle(event.target.value)} />
        </Field>
        <Field label="Prompt" htmlFor="task-prompt">
          <textarea
            id="task-prompt"
            value={prompt}
            onChange={(event) => setPrompt(event.target.value)}
            rows={3}
            className="w-full resize-y rounded-md border border-[var(--steel)] bg-[var(--hull)] p-2.5 text-base outline-none focus:border-[var(--signal)]"
          />
        </Field>
        <Field label="Starter code" htmlFor="task-starter">
          <textarea
            id="task-starter"
            value={starterCode}
            onChange={(event) => setStarterCode(event.target.value)}
            rows={4}
            spellCheck={false}
            className="mono w-full resize-y rounded-md border border-[var(--steel)] bg-[var(--hull)] p-2.5 text-sm outline-none focus:border-[var(--signal)]"
          />
        </Field>
        <Field label="Language" htmlFor="task-language">
          <select
            id="task-language"
            value={language}
            onChange={(event) => setLanguage(event.target.value as (typeof LANGUAGES)[number])}
            className="w-full rounded-md border border-[var(--steel)] bg-[var(--hull)] px-3 py-2.5 text-base outline-none focus:border-[var(--signal)]"
          >
            {LANGUAGES.map((lang) => (
              <option key={lang} value={lang}>
                {lang}
              </option>
            ))}
          </select>
        </Field>
        {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
        <Button disabled={busy || !title.trim() || !prompt.trim()} onClick={() => void submit()}>
          Assign task
        </Button>
      </div>
    </Card>
  );
}

function TaskWatcher({ sessionId, task }: { sessionId: string; task: CodingTask }) {
  const [source, setSource] = useState(task.starter_code);
  const [executions, setExecutions] = useState<CodeExecutionDetail[]>([]);

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      getCode(sessionId, task.id)
        .then((res) => {
          if (!cancelled) setSource(res.source);
        })
        .catch(() => undefined);
      listExecutions(sessionId, task.id)
        .then((res) => {
          if (!cancelled) setExecutions(res.executions);
        })
        .catch(() => undefined);
    }
    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId, task.id]);

  const latestExecution = executions[0] ?? null;

  return (
    <Card>
      <p className="text-sm font-semibold">{task.title}</p>
      <p className="mt-1 text-sm text-[var(--haze)]">{task.prompt}</p>
      <p className="mono mt-3 text-xs text-[var(--haze)]">live candidate code — read only</p>
      <pre className="mono mt-1 max-h-72 overflow-auto whitespace-pre-wrap rounded-md border border-[var(--steel)] bg-[var(--abyss)] p-3 text-sm">
        {source}
      </pre>
      {latestExecution && (
        <div className="mt-3">
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--haze)]">
            <Badge tone={latestExecution.exit_code === 0 ? "positive" : "negative"}>
              last run · exit {latestExecution.exit_code ?? "killed"}
            </Badge>
            <span>{latestExecution.duration_ms}ms</span>
          </div>
          {latestExecution.stdout && (
            <pre className="mono mt-2 whitespace-pre-wrap text-sm">{latestExecution.stdout}</pre>
          )}
        </div>
      )}
    </Card>
  );
}

function drawStroke(
  ctx: CanvasRenderingContext2D,
  canvas: HTMLCanvasElement,
  payload: StrokePayload,
): void {
  const [first, ...rest] = payload.points;
  if (!first || rest.length === 0) return;
  ctx.strokeStyle = payload.color;
  ctx.lineWidth = payload.width;
  ctx.lineCap = "round";
  ctx.lineJoin = "round";
  ctx.beginPath();
  ctx.moveTo(first[0] * canvas.width, first[1] * canvas.height);
  for (const [x, y] of rest) ctx.lineTo(x * canvas.width, y * canvas.height);
  ctx.stroke();
}

function WhiteboardViewer({ sessionId }: { sessionId: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [strokes, setStrokes] = useState<WhiteboardStroke[]>([]);
  const drawingRef = useRef<Array<[number, number]> | null>(null);

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      listWhiteboard(sessionId)
        .then((res) => {
          if (!cancelled) setStrokes(res.strokes);
        })
        .catch(() => undefined);
    }
    poll();
    const interval = setInterval(poll, 3000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId]);

  const redraw = useCallback(() => {
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    if (!canvas || !ctx) return;
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    for (const stroke of strokes) drawStroke(ctx, canvas, stroke.stroke_payload);
  }, [strokes]);

  useEffect(() => redraw(), [redraw]);

  function pointFromEvent(event: PointerEvent<HTMLCanvasElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [(event.clientX - rect.left) / rect.width, (event.clientY - rect.top) / rect.height];
  }

  function onPointerDown(event: PointerEvent<HTMLCanvasElement>): void {
    drawingRef.current = [pointFromEvent(event)];
  }

  function onPointerMove(event: PointerEvent<HTMLCanvasElement>): void {
    if (!drawingRef.current) return;
    const point = pointFromEvent(event);
    const canvas = canvasRef.current;
    const ctx = canvas?.getContext("2d");
    const previous = drawingRef.current[drawingRef.current.length - 1];
    if (ctx && canvas && previous) {
      ctx.strokeStyle = "#b3540f";
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(previous[0] * canvas.width, previous[1] * canvas.height);
      ctx.lineTo(point[0] * canvas.width, point[1] * canvas.height);
      ctx.stroke();
    }
    drawingRef.current.push(point);
  }

  function onPointerUp(): void {
    const points = drawingRef.current;
    drawingRef.current = null;
    if (!points || points.length < 2) return;
    addStroke(sessionId, { points, color: "#b3540f", width: 2 })
      .then((stroke) => setStrokes((current) => [...current, stroke]))
      .catch(() => undefined);
  }

  return (
    <Card>
      <p className="mb-2 text-sm font-semibold">Whiteboard</p>
      <canvas
        ref={canvasRef}
        width={800}
        height={400}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        className="w-full touch-none rounded-md border border-[var(--steel)] bg-white"
      />
      <p className="mt-2 text-xs text-[var(--haze)]">
        Shared live with the candidate — your strokes appear in orange.
      </p>
    </Card>
  );
}

function DiscussionThread({ sessionId }: { sessionId: string }) {
  const [messages, setMessages] = useState<DiscussionMessage[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      listDiscussion(sessionId)
        .then((res) => {
          if (!cancelled) setMessages(res.messages);
        })
        .catch(() => undefined);
    }
    poll();
    const interval = setInterval(poll, 4000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [sessionId]);

  async function send(): Promise<void> {
    const trimmed = body.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await postDiscussion(sessionId, trimmed);
      setBody("");
      setMessages((await listDiscussion(sessionId)).messages);
    } catch {
      // best-effort; the next poll reconciles state
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <p className="mb-2 text-sm font-semibold">Discussion</p>
      <ul className="flex max-h-64 flex-col gap-2 overflow-y-auto">
        {messages.length === 0 && <li className="text-sm text-[var(--haze)]">No messages yet.</li>}
        {messages.map((message) => (
          <li key={message.id} className="rounded-md border border-[var(--steel)] p-2 text-sm">
            <div className="flex items-center justify-between text-xs text-[var(--haze)]">
              <span className="font-semibold">
                {message.author === "interviewer" ? "You" : message.author_label}
              </span>
              <span>{new Date(message.created_at).toLocaleTimeString()}</span>
            </div>
            <p className="mt-1">{message.body}</p>
          </li>
        ))}
      </ul>
      <div className="mt-3 flex gap-2">
        <input
          value={body}
          onChange={(event) => setBody(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void send();
          }}
          placeholder="Reply to the candidate…"
          className="w-full rounded-md border border-[var(--steel)] bg-[var(--hull)] px-3 py-2 text-sm outline-none focus:border-[var(--signal)]"
        />
        <Button onClick={() => void send()} disabled={busy || !body.trim()}>
          Send
        </Button>
      </div>
    </Card>
  );
}
