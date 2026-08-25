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
  checks: Array<{ check: string; passed: boolean; detail: string }>;
  dimensions: ScoredDimension[];
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

export function login(email: string, password: string): Promise<LoginResponse> {
  return request<LoginResponse>("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
}

export function listCandidates(requisitionId: string): Promise<{ candidates: CandidateSummary[] }> {
  return request(`/requisitions/${requisitionId}/candidates`);
}

export function getResume(resumeId: string): Promise<ResumeDetail> {
  return request(`/resumes/${resumeId}`);
}

export function listRuns(requisitionId: string): Promise<{ runs: ScoringRunDetail[] }> {
  return request(`/requisitions/${requisitionId}/scoring-runs`);
}
