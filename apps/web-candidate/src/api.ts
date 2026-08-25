export interface DeviceCheck {
  kind: string;
  status: "ok" | "degraded" | "failed" | "missing";
  label: string;
}

export interface PreCheckReport {
  suite_version: string;
  devices: DeviceCheck[];
  connection: "good" | "fair" | "poor" | "unknown";
  bandwidth_kbps: number;
  browser: string;
}

export interface SessionState {
  status:
    | "pending_consent"
    | "consent_granted"
    | "precheck_passed"
    | "active"
    | "completed"
    | "aborted"
    | "declined";
  candidate_email: string;
  expires_at: string;
  consent: { required: boolean; version: string; statement: string };
  precheck: { suite_version: string; passed: boolean; report: Record<string, unknown> };
  progress: { asked_turns: number; plan_fingerprint: string | null };
  open_question: {
    kind: "question" | "probe" | "closing";
    topic_id: string | null;
    text: string;
  } | null;
}

export interface Question {
  kind: "question" | "probe" | "closing";
  topic_id: string | null;
  text: string;
  tts_text: string;
}

export interface TurnResult {
  status: SessionState["status"];
  transcript: { text: string } | null;
  stt: { confidence: number; model_id: string } | null;
  next: Question;
  completed: boolean;
}

export interface Synthesis {
  audio_b64: string;
  format: string;
  sample_rate: number;
  duration_seconds: number;
  text_sha256: string;
  provider: string;
  model_id: string;
}

const API_BASE = "/api";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, init);
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail.slice(0, 300));
  }
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function getSessionState(token: string): Promise<SessionState> {
  return request<SessionState>(`/public/interview-sessions/${encodeURIComponent(token)}`);
}

export function submitConsent(
  token: string,
  acceptedVersion: string,
  granted: boolean,
): Promise<{ status: string }> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/consent`, {
    accepted_version: acceptedVersion,
    granted,
  });
}

export function submitPrecheck(
  token: string,
  report: PreCheckReport,
): Promise<{ passed: boolean; failures: string[] }> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/precheck`, report);
}

export function startInterview(
  token: string,
): Promise<{ status: string; question: Question; progress_total: number }> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/start`, {});
}

export function submitTurnAnswer(
  token: string,
  answerText: string,
): Promise<TurnResult> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/turns`, {
    answer_text: answerText,
  });
}

export function submitTurnAudio(token: string, audioB64: string): Promise<TurnResult> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/turns`, {
    audio_b64: audioB64,
  });
}

export function finishInterview(token: string): Promise<{ status: string }> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/finish`, {});
}

export function speak(token: string, text: string): Promise<Synthesis> {
  return postJson(`/public/interview-sessions/${encodeURIComponent(token)}/tts`, { text });
}

export async function healthLatencyMs(): Promise<number> {
  const started = performance.now();
  await fetch(`${API_BASE}/healthz`, { cache: "no-store" });
  return Math.round(performance.now() - started);
}

export async function downloadThroughputKbps(): Promise<number> {
  const started = performance.now();
  const response = await fetch(`${API_BASE}/openapi.json`, { cache: "no-store" });
  const body = await response.text();
  const elapsedSeconds = (performance.now() - started) / 1000;
  if (elapsedSeconds <= 0) return 0;
  return Math.round((body.length * 8) / elapsedSeconds / 1000);
}
