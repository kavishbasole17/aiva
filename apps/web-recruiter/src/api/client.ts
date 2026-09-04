export interface LoginResponse {
  access_token: string;
  refresh_token: string;
}

export interface CandidateSummary {
  resume_id: string;
  filename: string;
  candidate_email: string | null;
  created_at: string;
  latest_run: {
    run_id: string;
    total_score: number;
    verdict: string;
    run_fingerprint: string;
  } | null;
}

export interface ResumeField {
  field_name: string;
  value: string;
  confidence: number;
  page_number: number;
  start_offset: number;
  end_offset: number;
  source_quote: string;
  extractor: string;
}

export interface ScoredDimension {
  dimension: string;
  score: number;
  evidence_refs: string[];
  rationale: string;
}

export interface ResumeDetail extends Record<string, unknown> {
  id: string;
  filename: string;
  page_count: number;
  candidate_email: string | null;
  fields: ResumeField[];
}

export interface ScoringRunDetail {
  id: string;
  total_score: number;
  verdict: string;
  run_fingerprint: string;
  // GET .../scoring-runs (the list endpoint) intentionally omits these —
  // only a single-run detail view would populate them. Never assume present.
  checks?: Array<{ check: string; passed: boolean; detail: string }>;
  dimensions?: ScoredDimension[];
}

export interface InterviewSessionSummary {
  id: string;
  candidate_email: string;
  status: string;
  precheck_passed: boolean;
  turn_count: number;
  started_at: string | null;
  finished_at: string | null;
  expires_at: string;
}

export interface InterviewTurnDetail {
  sequence: number;
  kind: string;
  topic_id: string | null;
  question_text: string;
  answer_text: string | null;
  stt_confidence: number | null;
  stt_model_id: string | null;
  tts_model_id: string | null;
  answer_audio_sha256: string | null;
}

export interface InterviewSessionDetail {
  id: string;
  candidate_email: string;
  status: string;
  plan_fingerprint: string | null;
  precheck_report: Record<string, unknown>;
  precheck_passed: boolean;
  turns: InterviewTurnDetail[];
  consents: Array<{ granted: boolean; consent_text_version: string; decided_at: string }>;
}

export interface EvaluationReport {
  id: string;
  candidate_email: string;
  requisition_title: string;
  overall_score: number;
  verdict: string;
  components: Array<{ name: string; score: number; detail: string }>;
  narrative: string | null;
  strengths: string[];
  concerns: string[];
  created_at: string;
}

export interface CodingTask {
  id: string;
  title: string;
  prompt: string;
  starter_code: string;
  language: string;
  created_at: string;
}

export interface CodeExecutionDetail {
  id: string;
  stdout: string;
  stderr: string;
  exit_code: number | null;
  timed_out: boolean;
  truncated: boolean;
  duration_ms: number;
  created_at: string;
}

export interface StrokePayload {
  points: Array<[number, number]>;
  color: string;
  width: number;
}

export interface WhiteboardStroke {
  id: string;
  author: "candidate" | "interviewer";
  stroke_payload: StrokePayload;
  created_at: string;
}

export interface DiscussionMessage {
  id: string;
  task_id: string | null;
  author: "candidate" | "interviewer";
  author_label: string;
  body: string;
  created_at: string;
}

export interface Department {
  id: string;
  name: string;
}

export interface RequisitionSummary {
  id: string;
  title: string;
  status: string;
  department_id: string;
  department_name: string;
}

export interface RequisitionDetail {
  id: string;
  title: string;
  status: string;
  version: number;
  department_id: string;
}

export interface JobDescriptionDetail {
  id: string;
  title: string;
  raw_text: string;
  required_skills: string[];
  preferred_skills: string[];
  min_years_experience: number;
}

export interface QuestionnaireQuestion {
  id: string;
  prompt: string;
  type: "multiple_choice" | "yes_no" | "rating" | "long_text" | "short_text" | "file_upload";
  required?: boolean;
  options?: string[];
}

export interface QuestionnaireSummary {
  id: string;
  title: string;
  question_count: number;
}

export interface QuestionnaireResponseSummary {
  id: string;
  candidate_email: string | null;
  submitted: boolean;
  submitted_at: string | null;
  missing_required: string[];
  history_entries: number;
  answers: Record<string, unknown>;
}

export interface InterviewSlotSummary {
  id: string;
  start_at: string;
  end_at: string;
  status: string;
  booked_for_email: string | null;
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

let accessToken: string | null = null;

export function setAccessToken(token: string | null): void {
  accessToken = token;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      ...(init?.headers ?? {}),
      ...(accessToken ? { Authorization: `Bearer ${accessToken}` } : {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new ApiError(response.status, detail.slice(0, 300));
  }
  if (response.status === 204) return {} as T;
  return (await response.json()) as T;
}

function postJson<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
}

export function login(email: string, password: string): Promise<LoginResponse> {
  return postJson<LoginResponse>("/auth/login", { email, password });
}

export interface CurrentUser {
  id: string;
  email: string;
  role: string;
  organization_id: string;
  mfa_enabled: boolean;
}

export function getMe(): Promise<CurrentUser> {
  return request("/me");
}

export function listCandidates(
  requisitionId: string,
  blind = false,
): Promise<{ candidates: CandidateSummary[] }> {
  return request(`/requisitions/${requisitionId}/candidates${blind ? "?blind=true" : ""}`);
}

export function getResume(resumeId: string, blind = false): Promise<ResumeDetail> {
  return request(`/resumes/${resumeId}${blind ? "?blind=true" : ""}`);
}

export interface DashboardStats {
  requisitions: { total: number; by_status: Record<string, number>; open: number };
  resumes: { total: number };
  scoring: { by_verdict: Record<string, number> };
  interviews: { by_status: Record<string, number> };
  questionnaires: { total: number; submitted: number; submission_rate: number | null };
  coding_tasks: { total: number; passed_latest_run: number; pass_rate: number | null };
}

export function getDashboard(organizationId: string): Promise<DashboardStats> {
  return request(`/orgs/${organizationId}/dashboard`);
}

export function listRuns(requisitionId: string): Promise<{ runs: ScoringRunDetail[] }> {
  return request(`/requisitions/${requisitionId}/scoring-runs`);
}

export function listInterviewSessions(
  requisitionId: string,
): Promise<{ sessions: InterviewSessionSummary[] }> {
  return request(`/requisitions/${requisitionId}/interview-sessions`);
}

export function getInterviewSession(sessionId: string): Promise<InterviewSessionDetail> {
  return request(`/interview-sessions/${sessionId}`);
}

export function listTasks(sessionId: string): Promise<{ tasks: CodingTask[] }> {
  return request(`/interview-sessions/${sessionId}/coding-tasks`);
}

export function createTask(
  sessionId: string,
  body: { title: string; prompt: string; starter_code: string; language: string },
): Promise<CodingTask> {
  return postJson(`/interview-sessions/${sessionId}/coding-tasks`, body);
}

export function getCode(sessionId: string, taskId: string): Promise<{ source: string }> {
  return request(`/interview-sessions/${sessionId}/coding-tasks/${taskId}/code`);
}

export function listExecutions(
  sessionId: string,
  taskId: string,
): Promise<{ executions: CodeExecutionDetail[] }> {
  return request(`/interview-sessions/${sessionId}/coding-tasks/${taskId}/executions`);
}

export function listWhiteboard(sessionId: string): Promise<{ strokes: WhiteboardStroke[] }> {
  return request(`/interview-sessions/${sessionId}/whiteboard`);
}

export function addStroke(
  sessionId: string,
  strokePayload: StrokePayload,
): Promise<WhiteboardStroke> {
  return postJson(`/interview-sessions/${sessionId}/whiteboard`, { stroke_payload: strokePayload });
}

export function listDiscussion(sessionId: string): Promise<{ messages: DiscussionMessage[] }> {
  return request(`/interview-sessions/${sessionId}/discussion`);
}

export function postDiscussion(sessionId: string, body: string): Promise<DiscussionMessage> {
  return postJson(`/interview-sessions/${sessionId}/discussion`, { body });
}

export function getIntegritySignals(
  sessionId: string,
): Promise<{ signals: Array<{ signal_type: string; created_at: string }>; summary: Record<string, number> }> {
  return request(`/interview-sessions/${sessionId}/integrity-signals`);
}

export function generateEvaluation(
  requisitionId: string,
  resumeId: string,
): Promise<EvaluationReport> {
  return postJson(`/requisitions/${requisitionId}/resumes/${resumeId}/evaluation`, {});
}

export async function getLatestEvaluation(
  requisitionId: string,
  resumeId: string,
): Promise<EvaluationReport | null> {
  try {
    return await request<EvaluationReport>(
      `/requisitions/${requisitionId}/resumes/${resumeId}/evaluation`,
    );
  } catch (cause) {
    if (cause instanceof ApiError && cause.status === 404) return null;
    throw cause;
  }
}

// --- Org / departments / requisitions ---

export function listDepartments(organizationId: string): Promise<{ departments: Department[] }> {
  return request(`/orgs/${organizationId}/departments`);
}

export function createDepartment(organizationId: string, name: string): Promise<Department> {
  return postJson(`/orgs/${organizationId}/departments`, { name });
}

export function listRequisitions(
  organizationId: string,
): Promise<{ requisitions: RequisitionSummary[] }> {
  return request(`/orgs/${organizationId}/requisitions`);
}

export function createRequisition(
  departmentId: string,
  title: string,
): Promise<RequisitionDetail> {
  return postJson(`/departments/${departmentId}/requisitions`, {
    title,
    department_id: departmentId,
  });
}

export function getRequisition(requisitionId: string): Promise<RequisitionDetail> {
  return request(`/requisitions/${requisitionId}`);
}

// --- Job descriptions ---

export function getJobDescription(
  requisitionId: string,
): Promise<JobDescriptionDetail | null> {
  return request(`/requisitions/${requisitionId}/job-description`);
}

export function createJobDescription(
  requisitionId: string,
  body: {
    title: string;
    raw_text: string;
    required_skills: string[];
    preferred_skills: string[];
    min_years_experience: number;
  },
): Promise<{ id: string; title: string }> {
  return postJson(`/requisitions/${requisitionId}/job-description`, body);
}

// --- Resume upload + scoring ---

export async function uploadResume(
  requisitionId: string,
  file: File,
): Promise<{ id: string; field_count: number; page_count: number }> {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch(`${API_BASE}/requisitions/${requisitionId}/resumes`, {
    method: "POST",
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
    body: form,
  });
  if (!response.ok) {
    throw new ApiError(response.status, (await response.text()).slice(0, 300));
  }
  return (await response.json()) as { id: string; field_count: number; page_count: number };
}

export function createWeightProfile(
  requisitionId: string,
  body: {
    name: string;
    weights: Record<string, number>;
    auto_reject_below: number;
    hold_below: number;
    highly_recommended_at: number;
  },
): Promise<{ id: string }> {
  return postJson(`/requisitions/${requisitionId}/weight-profiles`, body);
}

export function runScoring(
  requisitionId: string,
  resumeId: string,
  weightProfileId: string,
): Promise<{ id: string; total_score: number; verdict: string }> {
  return postJson(`/requisitions/${requisitionId}/scoring-runs`, {
    resume_id: resumeId,
    weight_profile_id: weightProfileId,
  });
}

// --- Questionnaires ---

export function listQuestionnaires(
  requisitionId: string,
): Promise<{ questionnaires: QuestionnaireSummary[] }> {
  return request(`/requisitions/${requisitionId}/questionnaires`);
}

export function createQuestionnaire(
  requisitionId: string,
  title: string,
  questions: QuestionnaireQuestion[],
): Promise<{ id: string; question_count: number }> {
  return postJson(`/requisitions/${requisitionId}/questionnaires`, { title, questions });
}

export function createQuestionnaireInvite(
  questionnaireId: string,
  candidateEmail: string,
): Promise<{ invite_id: string; token: string; expires_at: string }> {
  return postJson(`/questionnaires/${questionnaireId}/invites`, {
    candidate_email: candidateEmail,
  });
}

export function listQuestionnaireResponses(
  requisitionId: string,
): Promise<{ responses: QuestionnaireResponseSummary[] }> {
  return request(`/requisitions/${requisitionId}/questionnaire-responses`);
}

// --- Scheduling ---

export function generateSlots(
  requisitionId: string,
  body: {
    date_from: string;
    date_to: string;
    timezone_name: string;
    local_start: string;
    local_end: string;
    duration_minutes: number;
    buffer_minutes: number;
    include_weekends: boolean;
  },
): Promise<{ created: number }> {
  return postJson(`/requisitions/${requisitionId}/slots/generate`, body);
}

export function listSlots(
  requisitionId: string,
): Promise<{ slots: InterviewSlotSummary[] }> {
  return request(`/requisitions/${requisitionId}/slots`);
}

export function bookSlot(
  slotId: string,
  candidateEmail: string,
): Promise<{ id: string; status: string; ics: string }> {
  return postJson(`/slots/${slotId}/book`, { candidate_email: candidateEmail });
}

export function createInterviewSessionForSlot(
  slotId: string,
  resumeId?: string,
): Promise<{ id: string; token: string }> {
  return postJson(`/slots/${slotId}/interview-session`, resumeId ? { resume_id: resumeId } : {});
}

export async function downloadEvaluationExport(
  reportId: string,
  format: "pdf" | "xlsx",
): Promise<void> {
  const response = await fetch(`${API_BASE}/evaluation-reports/${reportId}/export.${format}`, {
    headers: accessToken ? { Authorization: `Bearer ${accessToken}` } : {},
  });
  if (!response.ok) {
    throw new ApiError(response.status, await response.text());
  }
  const blob = await response.blob();
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `evaluation-${reportId}.${format}`;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}
