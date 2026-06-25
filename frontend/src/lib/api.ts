/**
 * API client — typed fetch wrapper for all backend endpoints.
 *
 * Uses relative paths so the Vite dev-server proxy forwards
 * /api/* requests to the FastAPI backend at localhost:8000.
 */

// ── Types ────────────────────────────────────────────────────────────────────

export type ContractStatus = "new" | "reviewed" | "drafting" | "applied" | "skipped";
export type ContractType = "hourly" | "fixed";
export type Indicator = "green" | "yellow" | "red";
export type ScannerState = "idle" | "running" | "complete" | "error";
export type SubmissionChannel = "direct" | "browser" | "auto";
export type ProposalStatus = "draft" | "approved" | "submitted";
export type ApplicationOutcome =
  | "submitted"
  | "viewed"
  | "interview"
  | "hired"
  | "rejected"
  | "no_response";

export interface ContractResponse {
  id: number;
  platform: string;
  external_id: string;
  url: string | null;
  title: string | null;
  description: string | null;
  skills_required: string[] | null;
  budget_min: number | null;
  budget_max: number | null;
  contract_type: ContractType | null;
  duration: string | null;
  proposals_count: number | null;
  client_hire_rate: number | null;
  client_total_spent: number | null;
  client_location: string | null;
  match_score: number | null;
  roi_score: number | null;
  connects_cost: number | null;
  client_questions: string[] | null;
  status: ContractStatus;
  posted_at: string | null;
  fetched_at: string | null;
  indicator: Indicator;
  source: string | null;
  description_fit: number | null;
  skip_reason: string | null;
  is_finalist: boolean;
}

export interface ScannerStatus {
  state: ScannerState;
  contracts_found: number;
  current_search: string | null;
  progress: number;
  errors: string[];
  started_at: string | null;
}

export interface Proposal {
  id: number;
  contract_id: number;
  version: number;
  content: string | null;
  sections: ProposalSection[] | null;
  matched_case_studies: string[] | null;
  bid_amount: number | null;
  estimated_duration: string | null;
  status: ProposalStatus;
  created_at: string | null;
  submitted_at: string | null;
}

export interface ProposalSection {
  type: string;
  content: string;
  annotation: string | null;
  case_study_ids: string[] | null;
}

export interface ProposalUpdateBody {
  content?: string;
  sections?: ProposalSection[];
  bid_amount?: number;
  estimated_duration?: string;
}

export interface AvailabilityConfig {
  hours_per_week: number;
  max_concurrent_contracts: number;
  current_committed_hours: number;
  preferred_duration: string;
  preferred_contract_type: string;
  min_hourly_rate: number;
  min_fixed_budget: number;
  hourly_value: number;
}

export interface HistoryEntry {
  id: number;
  contract_id: number;
  proposal_id: number;
  connects_spent: number | null;
  outcome: ApplicationOutcome;
  submitted_at: string | null;
  outcome_at: string | null;
}

export interface HistoryCreateBody {
  contract_id: number;
  proposal_id: number;
  connects_spent?: number;
  outcome?: ApplicationOutcome;
}

export interface HistoryStats {
  total_applications: number;
  connects_spent: number;
  response_rate: number;
  outcomes_breakdown: Record<string, number>;
}

export interface ContractFilters {
  status?: ContractStatus;
  contract_type?: ContractType;
  min_roi?: number;
  budget_min?: number;
  budget_max?: number;
  skill?: string;
}

export type BudgetPeriod = "week";

export interface BudgetConfig {
  connects_per_period: number;
  generation_apps_per_period: number;
  generation_dollars_per_period: number;
  period: BudgetPeriod;
  per_run_max_apps: number | null;
}

export interface BudgetUsage {
  connects: number;
  generation_apps: number;
  generation_dollars: number;
}

export interface BudgetStatus {
  config: BudgetConfig;
  used: BudgetUsage;
  remaining: BudgetUsage;
  period_start: string;
}

export interface FinalistItem {
  id: number;
  title: string | null;
  kind: string;
  platform: string;
  job_priority: number;
  connects_cost: number;
}

export interface DeferredItem {
  id: number;
  title: string | null;
  reason: string;
}

export interface AwaitingSubmitItem {
  id: number;
  title: string | null;
  detail: string;
}

export interface PlanResult {
  will_process: FinalistItem[];
  deferred: DeferredItem[];
  totals: BudgetUsage;
}

export interface RunResult {
  processed: FinalistItem[];
  deferred: DeferredItem[];
  awaiting_submit: AwaitingSubmitItem[];
  remaining: BudgetUsage;
}

export type JobBucket = "skipped" | "candidate" | "finalist" | "applied";

export interface JobListItem {
  id: number;
  title: string | null;
  url: string | null;
  platform: string;
  company: string | null;
  location: string | null;
  work_mode: "remote" | "location";
  description_excerpt: string | null;
  skills_required: string[] | null;
  match_score: number | null;
  description_fit: number | null;
  job_priority: number;
  bucket: JobBucket;
  applied_at: string | null;
  flag_count: number;
  skip_reason: string | null;
  is_finalist: boolean;
  submission_channel?: SubmissionChannel;
  feedback: "liked" | "disliked" | null;
}

export interface JobScreeningAnswer {
  question: string;
  answer: string;
}

export interface JobDetail {
  id: number;
  title: string | null;
  url: string | null;
  platform: string;
  company: string | null;
  location: string | null;
  work_mode: "remote" | "location";
  description: string | null;
  description_excerpt: string | null;
  skills_required: string[] | null;
  match_score: number | null;
  description_fit: number | null;
  job_priority: number;
  bucket: JobBucket;
  skip_reason: string | null;
  cover_letter: string | null;
  screening_answers: JobScreeningAnswer[] | null;
  review_flags: Record<string, unknown>[] | null;
  generated_at: string | null;
  applied: boolean;
  applied_at: string | null;
  is_finalist: boolean;
  submission_channel?: SubmissionChannel;
  feedback: "liked" | "disliked" | null;
}

// ── Helpers ──────────────────────────────────────────────────────────────────

class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text().catch(() => res.statusText);
    throw new ApiError(res.status, text);
  }
  return res.json() as Promise<T>;
}

function qs(params: Record<string, string | number | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string | number] => entry[1] !== undefined,
  );
  if (entries.length === 0) return "";
  return "?" + new URLSearchParams(entries.map(([k, v]) => [k, String(v)])).toString();
}

// ── Contract endpoints ───────────────────────────────────────────────────────

export async function getContracts(
  filters?: ContractFilters,
): Promise<ContractResponse[]> {
  const query = filters
    ? qs({
        status: filters.status,
        contract_type: filters.contract_type,
        min_roi: filters.min_roi,
        budget_min: filters.budget_min,
        budget_max: filters.budget_max,
        skill: filters.skill,
      })
    : "";
  return request<ContractResponse[]>(`/api/contracts${query}`);
}

export async function getContract(id: number): Promise<ContractResponse> {
  return request<ContractResponse>(`/api/contracts/${id}`);
}

// ── Scanner endpoints ────────────────────────────────────────────────────────

export async function scanContracts(): Promise<{ state: string; message?: string }> {
  return request<{ state: string; message?: string }>("/api/scanner/scan", {
    method: "POST",
  });
}

export async function getScannerStatus(): Promise<ScannerStatus> {
  return request<ScannerStatus>("/api/scanner/status");
}

export async function scanJobBoards(): Promise<ScannerStatus> {
  return request<ScannerStatus>("/api/scanner/jobs", { method: "POST" });
}

export async function getJobScanStatus(): Promise<ScannerStatus> {
  return request<ScannerStatus>("/api/scanner/jobs/status");
}

// ── Enrichment endpoints ────────────────────────────────────────────────────

export interface EnrichBatchResult {
  enriched: number;
  skipped: number;
  failed: number;
  errors: string[];
}

export async function enrichBatch(): Promise<EnrichBatchResult> {
  return request<EnrichBatchResult>("/api/contracts/enrich/batch", {
    method: "POST",
  });
}

// ── Proposal endpoints ───────────────────────────────────────────────────────

export async function createProposal(contractId: number): Promise<Proposal> {
  return request<Proposal>(`/api/contracts/${contractId}/propose`, {
    method: "POST",
  });
}

export async function getProposal(id: number): Promise<Proposal> {
  return request<Proposal>(`/api/proposals/${id}`);
}

export async function updateProposal(
  id: number,
  data: ProposalUpdateBody,
): Promise<Proposal> {
  return request<Proposal>(`/api/proposals/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function fillProposal(
  id: number,
): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>(
    `/api/proposals/${id}/fill`,
    { method: "POST" },
  );
}

// ── Availability endpoints ───────────────────────────────────────────────────

export async function getAvailability(): Promise<AvailabilityConfig> {
  return request<AvailabilityConfig>("/api/availability");
}

export async function updateAvailability(
  data: AvailabilityConfig,
): Promise<AvailabilityConfig> {
  return request<AvailabilityConfig>("/api/availability", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

// ── History endpoints ────────────────────────────────────────────────────────

export async function getHistory(): Promise<HistoryEntry[]> {
  return request<HistoryEntry[]>("/api/history");
}

export async function createHistoryEntry(
  data: HistoryCreateBody,
): Promise<HistoryEntry> {
  return request<HistoryEntry>("/api/history", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function getHistoryStats(): Promise<HistoryStats> {
  return request<HistoryStats>("/api/history/stats");
}

// ── Job endpoints ────────────────────────────────────────────────────────────

export async function listJobs(): Promise<JobListItem[]> {
  return request<JobListItem[]>("/api/jobs");
}

export async function getJob(id: number): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}`);
}

export async function updateJobApplication(
  id: number,
  data: { cover_letter: string; screening_answers?: JobScreeningAnswer[] | null },
): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/application`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data),
  });
}

export async function fillPreparedJobApplication(
  id: number,
): Promise<{ filled: boolean; submitted: boolean; detail: string }> {
  return request<{ filled: boolean; submitted: boolean; detail: string }>(
    `/api/jobs/${id}/fill`,
    { method: "POST" },
  );
}

export async function setJobApplied(
  id: number,
  applied: boolean,
): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/applied`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ applied }),
  });
}

export type JobFeedback = "liked" | "disliked" | null;

export async function setJobFeedback(
  id: number,
  feedback: JobFeedback,
): Promise<JobDetail> {
  return request<JobDetail>(`/api/jobs/${id}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ feedback }),
  });
}

export interface SkillWeight {
  skill: string;
  weight: number;
}

export async function getPreferences(): Promise<SkillWeight[]> {
  const data = await request<{ weights: SkillWeight[] }>("/api/preferences");
  return data.weights;
}

// ── Budget endpoints ──────────────────────────────────────────────────────────

export async function getBudget(): Promise<BudgetStatus> {
  return request<BudgetStatus>("/api/budget");
}

export async function updateBudget(config: BudgetConfig): Promise<BudgetStatus> {
  return request<BudgetStatus>("/api/budget", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(config),
  });
}

// ── Finalist endpoints ────────────────────────────────────────────────────────

export async function setFinalist(id: number, isFinalist: boolean): Promise<{ id: number; is_finalist: boolean }> {
  return request(`/api/opportunities/${id}/finalist`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ is_finalist: isFinalist }),
  });
}

export async function listFinalists(): Promise<FinalistItem[]> {
  return request<FinalistItem[]>("/api/finalists");
}

export async function planApply(perRunMaxApps: number | null): Promise<PlanResult> {
  return request<PlanResult>("/api/finalists/plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ per_run_max_apps: perRunMaxApps }),
  });
}

export async function runApply(perRunMaxApps: number | null): Promise<RunResult> {
  return request<RunResult>("/api/finalists/apply", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ per_run_max_apps: perRunMaxApps }),
  });
}

// ── Profile endpoints ─────────────────────────────────────────────────────────

export async function getProfileYaml(): Promise<string> {
  const res = await fetch("/api/profile");
  if (!res.ok) throw new Error(`getProfileYaml failed: ${res.status}`);
  return (await res.json()).yaml as string;
}

export async function putProfileYaml(yaml: string): Promise<void> {
  const res = await fetch("/api/profile", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ yaml }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => ({}));
    throw new Error(detail.detail || `putProfileYaml failed: ${res.status}`);
  }
}
