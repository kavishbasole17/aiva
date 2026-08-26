import { Badge, Button, Card, EmptyState } from "@aiva/ui";
import type { KeyboardEvent, PointerEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  addStroke,
  askFaq,
  getCode,
  listDiscussion,
  listTasks,
  listWhiteboard,
  postDiscussion,
  runCode,
  saveCode,
} from "../api";
import type {
  CodingTask,
  DiscussionMessage,
  ExecutionResult,
  FaqAnswer,
  StrokePayload,
  WhiteboardStroke,
} from "../api";

type Tab = "code" | "whiteboard" | "discussion" | "faq";
const TABS: Tab[] = ["code", "whiteboard", "discussion", "faq"];

export function WorkspacePanel({ token }: { token: string }) {
  const [tasks, setTasks] = useState<CodingTask[] | null>(null);
  const [activeTaskId, setActiveTaskId] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("code");

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      listTasks(token)
        .then((res) => {
          if (cancelled) return;
          setTasks(res.tasks);
          setActiveTaskId((current) => current ?? res.tasks[0]?.id ?? null);
        })
        .catch(() => undefined);
    }
    poll();
    const interval = setInterval(poll, 5000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, [token]);

  if (tasks === null) {
    return <p className="text-sm text-[var(--haze)]">Loading workspace…</p>;
  }

  const activeTask = tasks.find((task) => task.id === activeTaskId) ?? tasks[0] ?? null;

  return (
    <div className="flex flex-col gap-4">
      {tasks.length > 1 && (
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

      <div className="flex gap-2 border-b border-[var(--steel)] pb-2">
        {TABS.map((candidate) => (
          <button
            key={candidate}
            type="button"
            onClick={() => setTab(candidate)}
            className={`rounded-md px-3 py-1.5 text-sm font-medium capitalize transition-colors ${
              tab === candidate
                ? "bg-[var(--signal)] text-white"
                : "text-[var(--haze)] hover:text-[var(--mist)]"
            }`}
          >
            {candidate}
          </button>
        ))}
      </div>

      {tab === "code" &&
        (activeTask ? (
          <CodeTab token={token} task={activeTask} />
        ) : (
          <EmptyState
            title="No coding task yet"
            body="Your interviewer hasn't assigned a coding exercise. The whiteboard and discussion tabs are open any time."
          />
        ))}
      {tab === "whiteboard" && <WhiteboardTab token={token} />}
      {tab === "discussion" && <DiscussionTab token={token} />}
      {tab === "faq" && <FaqTab token={token} />}
    </div>
  );
}

function FaqTab({ token }: { token: string }) {
  const [question, setQuestion] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [history, setHistory] = useState<Array<{ question: string; answer: FaqAnswer }>>([]);

  async function ask(): Promise<void> {
    const trimmed = question.trim();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const answer = await askFaq(token, trimmed);
      setHistory((current) => [...current, { question: trimmed, answer }]);
      setQuestion("");
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Could not get an answer");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <p className="text-sm text-[var(--haze)]">
        Ask about the role, process, or format — answered from your recruiter's FAQ
        documents only.
      </p>
      <ul className="flex flex-col gap-3">
        {history.map((entry, index) => (
          <li key={index} className="flex flex-col gap-2">
            <p className="text-sm font-semibold">{entry.question}</p>
            <Card>
              <p className="text-sm leading-relaxed">{entry.answer.answer}</p>
              {entry.answer.retrieved.length > 0 && (
                <p className="mt-2 text-xs text-[var(--haze)]">
                  Sourced from: {entry.answer.retrieved.map((doc) => doc.title).join(", ")}
                </p>
              )}
            </Card>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          value={question}
          onChange={(event) => setQuestion(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void ask();
          }}
          placeholder="e.g. How long does the interview take?"
          className="w-full rounded-md border border-[var(--steel)] bg-[var(--abyss)] px-3 py-2 text-sm outline-none focus:border-[var(--signal)]"
        />
        <Button onClick={() => void ask()} disabled={busy || !question.trim()}>
          {busy ? "Asking…" : "Ask"}
        </Button>
      </div>
      {error && <p className="text-sm text-[var(--danger)]">{error}</p>}
    </div>
  );
}

function CodeTab({ token, task }: { token: string; task: CodingTask }) {
  const [source, setSource] = useState(task.starter_code);
  const [status, setStatus] = useState<"loading" | "saved" | "saving">("loading");
  const [running, setRunning] = useState(false);
  const [result, setResult] = useState<ExecutionResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const saveTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setStatus("loading");
    setResult(null);
    getCode(token, task.id)
      .then((res) => {
        setSource(res.source);
        setStatus("saved");
      })
      .catch(() => setStatus("saved"));
    return () => {
      if (saveTimer.current) clearTimeout(saveTimer.current);
    };
  }, [token, task.id]);

  function onChange(value: string): void {
    setSource(value);
    setStatus("saving");
    if (saveTimer.current) clearTimeout(saveTimer.current);
    saveTimer.current = setTimeout(() => {
      saveCode(token, task.id, value)
        .then(() => setStatus("saved"))
        .catch(() => setStatus("saved"));
    }, 800);
  }

  function onKeyDown(event: KeyboardEvent<HTMLTextAreaElement>): void {
    if (event.key !== "Tab") return;
    event.preventDefault();
    const target = event.currentTarget;
    const start = target.selectionStart;
    const end = target.selectionEnd;
    const next = `${source.slice(0, start)}    ${source.slice(end)}`;
    onChange(next);
    requestAnimationFrame(() => {
      target.selectionStart = start + 4;
      target.selectionEnd = start + 4;
    });
  }

  async function run(): Promise<void> {
    setRunning(true);
    setError(null);
    try {
      setResult(await runCode(token, task.id, source));
    } catch (exception) {
      setError(exception instanceof Error ? exception.message : "Run failed");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div>
        <p className="text-sm font-semibold">{task.title}</p>
        <p className="mt-1 text-sm text-[var(--haze)]">{task.prompt}</p>
      </div>
      <div className="flex items-center justify-between text-xs text-[var(--haze)]">
        <span className="mono">{task.language}</span>
        <span>{status === "saving" ? "Saving…" : status === "loading" ? "Loading…" : "Saved"}</span>
      </div>
      <textarea
        value={source}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={onKeyDown}
        spellCheck={false}
        rows={16}
        className="mono w-full resize-y rounded-md border border-[var(--steel)] bg-[var(--abyss)] p-3 leading-relaxed outline-none focus:border-[var(--signal)]"
      />
      <div className="flex items-center justify-between">
        <Button onClick={() => void run()} disabled={running}>
          {running ? "Running…" : "Run code"}
        </Button>
        {error && <span className="text-sm text-[var(--danger)]">{error}</span>}
      </div>
      {result && (
        <Card>
          <div className="flex flex-wrap items-center gap-2 text-xs text-[var(--haze)]">
            <Badge tone={result.exit_code === 0 ? "positive" : "negative"}>
              exit {result.exit_code ?? "killed"}
            </Badge>
            {result.timed_out && <Badge tone="warning">timed out</Badge>}
            {result.truncated && <Badge tone="warning">output truncated</Badge>}
            <span>{result.duration_ms}ms</span>
          </div>
          {result.stdout && (
            <pre className="mono mt-2 whitespace-pre-wrap text-sm">{result.stdout}</pre>
          )}
          {result.stderr && (
            <pre className="mono mt-2 whitespace-pre-wrap text-sm text-[var(--danger)]">
              {result.stderr}
            </pre>
          )}
        </Card>
      )}
    </div>
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
  for (const [x, y] of rest) {
    ctx.lineTo(x * canvas.width, y * canvas.height);
  }
  ctx.stroke();
}

function WhiteboardTab({ token }: { token: string }) {
  const canvasRef = useRef<HTMLCanvasElement | null>(null);
  const [strokes, setStrokes] = useState<WhiteboardStroke[]>([]);
  const drawingRef = useRef<Array<[number, number]> | null>(null);

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      listWhiteboard(token)
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
  }, [token]);

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
      const [prevX, prevY] = previous;
      ctx.strokeStyle = "#0a2f5c";
      ctx.lineWidth = 2;
      ctx.lineCap = "round";
      ctx.beginPath();
      ctx.moveTo(prevX * canvas.width, prevY * canvas.height);
      ctx.lineTo(point[0] * canvas.width, point[1] * canvas.height);
      ctx.stroke();
    }
    drawingRef.current.push(point);
  }

  function onPointerUp(): void {
    const points = drawingRef.current;
    drawingRef.current = null;
    if (!points || points.length < 2) return;
    addStroke(token, { points, color: "#0a2f5c", width: 2 })
      .then((stroke) => setStrokes((current) => [...current, stroke]))
      .catch(() => undefined);
  }

  return (
    <div className="flex flex-col gap-2">
      <canvas
        ref={canvasRef}
        width={800}
        height={450}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        className="w-full touch-none rounded-md border border-[var(--steel)] bg-white"
      />
      <p className="text-xs text-[var(--haze)]">
        Draw with mouse or touch — synced with your interviewer.
      </p>
    </div>
  );
}

function DiscussionTab({ token }: { token: string }) {
  const [messages, setMessages] = useState<DiscussionMessage[]>([]);
  const [body, setBody] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    function poll(): void {
      listDiscussion(token)
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
  }, [token]);

  async function send(): Promise<void> {
    const trimmed = body.trim();
    if (!trimmed) return;
    setBusy(true);
    try {
      await postDiscussion(token, trimmed);
      setBody("");
      setMessages((await listDiscussion(token)).messages);
    } catch {
      // best-effort; the next poll reconciles state
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <ul className="flex max-h-72 flex-col gap-2 overflow-y-auto">
        {messages.length === 0 && <li className="text-sm text-[var(--haze)]">No messages yet.</li>}
        {messages.map((message) => (
          <li key={message.id} className="rounded-md border border-[var(--steel)] p-2 text-sm">
            <div className="flex items-center justify-between text-xs text-[var(--haze)]">
              <span className="font-semibold">
                {message.author === "candidate" ? "You" : message.author_label}
              </span>
              <span>{new Date(message.created_at).toLocaleTimeString()}</span>
            </div>
            <p className="mt-1">{message.body}</p>
          </li>
        ))}
      </ul>
      <div className="flex gap-2">
        <input
          value={body}
          onChange={(event) => setBody(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") void send();
          }}
          placeholder="Ask a question…"
          className="w-full rounded-md border border-[var(--steel)] bg-[var(--abyss)] px-3 py-2 text-sm outline-none focus:border-[var(--signal)]"
        />
        <Button onClick={() => void send()} disabled={busy || !body.trim()}>
          Send
        </Button>
      </div>
    </div>
  );
}
