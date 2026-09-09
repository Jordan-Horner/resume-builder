import type { Application, GmailSetup, HiddenJobResult, Integration, Job, JobFeedback, JobFeedbackAction, JobFeedbackReason, JobFilters, JobHideReason, JobScreenResult, JobScreenState, OnboardingStatus, ResumeLibrary, ResumeRecommendation, SalaryEstimateResult, SearchPreferences, TelegramPairing } from "./types";

export interface UpdateStatus {
  version: string;
  revision: string;
  channel: string;
  built_at: string;
  status: "development" | "up_to_date" | "update_available" | "ahead" | "unavailable";
  latest_revision: string | null;
  release_url: string;
  last_success_at: string | null;
  message: string;
}
export function getUpdateStatus(): Promise<UpdateStatus> { return request("/api/system/version"); }

export interface SystemComponent {
  id: "portal" | "scheduler" | "workspace-sync" | "telegram";
  name: string;
  status: "online" | "offline" | "disabled" | "not_configured" | "error" | "unknown" | "waiting" | "checking" | "stale" | "current" | "updated" | "blocked";
  detail: string;
}
export interface SystemStatus {
  status: "healthy" | "degraded";
  components: SystemComponent[];
}
export function getSystemStatus(): Promise<SystemStatus> { return request("/api/system/status"); }

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
    throw new Error(payload?.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return undefined as T;
  if (!response.headers.get("content-type")?.includes("application/json")) {
    throw new Error("The portal and server are out of sync. Refresh the page or restart the portal.");
  }
  return response.json() as Promise<T>;
}

async function requestWithTimeout<T>(
  url: string,
  init: RequestInit,
  timeoutMs: number,
  timeoutMessage: string,
): Promise<T> {
  const controller = new AbortController();
  const upstreamSignal = init.signal;
  let timedOut = false;
  const abortFromUpstream = () => controller.abort();
  if (upstreamSignal?.aborted) controller.abort();
  else upstreamSignal?.addEventListener("abort", abortFromUpstream, { once: true });
  const timeout = globalThis.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  try {
    return await request<T>(url, { ...init, signal: controller.signal });
  } catch (error) {
    if (timedOut) throw new Error(timeoutMessage);
    throw error;
  } finally {
    globalThis.clearTimeout(timeout);
    upstreamSignal?.removeEventListener("abort", abortFromUpstream);
  }
}

export async function getJobs(filters: JobFilters, queue: "all" | "recommended" | "interested" = "all", signal?: AbortSignal): Promise<{ jobs: Job[]; count: number; reviewable_count: number }> {
  const params = new URLSearchParams();
  if (filters.view) params.set("view_filters", JSON.stringify({ ...filters.view, roles: [], locations: filters.view.locations.map((item) => item.trim()).filter(Boolean) }));
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.workMode) params.set("work_mode", filters.workMode);
  if (filters.dateDays) params.set("date_days", String(filters.dateDays));
  if (filters.employmentType) params.set("employment_type", filters.employmentType);
  if (queue !== "all") params.set("queue", queue);
  return request<{ jobs: Job[]; count: number; reviewable_count: number }>(`/api/jobs?${params.toString()}`, signal ? { signal } : undefined);
}

export function getJob(jobId: string, signal?: AbortSignal): Promise<Job> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}`,
    signal ? { signal } : {},
    8_000,
    "Loading this job took too long. Try opening it again.",
  );
}

export function markJobNotInterested(jobId: string): Promise<JobFeedback> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/not-interested`,
    { method: "POST" },
    10_000,
    "Saving took too long. Please try again.",
  );
}

export function hideJobPosting(jobId: string, reason: JobHideReason): Promise<HiddenJobResult> {
  return requestWithTimeout(`/api/jobs/${encodeURIComponent(jobId)}/hide`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ reason }),
  }, 10_000, "Hiding this posting took too long. Please try again.");
}

export function getJobFeedback(jobId: string, signal?: AbortSignal): Promise<JobFeedback> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/feedback`,
    signal ? { signal } : {},
    8_000,
    "Loading your job preference took too long.",
  );
}

export function saveJobFeedback(jobId: string, action: JobFeedbackAction, reasons: JobFeedbackReason[]): Promise<JobFeedback> {
  return requestWithTimeout(`/api/jobs/${encodeURIComponent(jobId)}/feedback`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ action, reasons }),
  }, 10_000, "Saving took too long. Please try again.");
}

export function recordJobPostingOpened(jobId: string): Promise<void> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/opened-posting`, { method: "POST", keepalive: true });
}

export function estimateJobSalary(jobId: string): Promise<SalaryEstimateResult> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/estimate-salary`,
    { method: "POST" },
    30_000,
    "Salary estimation took too long. Please try again.",
  );
}

export async function getSavedJobSalary(jobId: string): Promise<SalaryEstimateResult | null> {
  return (await requestWithTimeout<SalaryEstimateResult | null>(
    `/api/jobs/${encodeURIComponent(jobId)}/salary-estimate`,
    {},
    8_000,
    "Loading the saved salary estimate took too long.",
  )) ?? null;
}

export function markJobApplied(jobId: string, resumeId?: string): Promise<unknown> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/applied`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ resume_id: resumeId ?? null }),
    },
    10_000,
    "Saving the application took too long. Please try again.",
  );
}

export async function getApplications(): Promise<Application[]> {
  const payload = await request<{ applications: Application[] }>("/api/applications");
  return payload.applications;
}

export function markApplicationReapplied(applicationId: string): Promise<unknown> {
  return request(`/api/applications/${encodeURIComponent(applicationId)}/reapplied`, { method: "POST" });
}

export async function getIntegrations(): Promise<Integration[]> {
  const payload = await request<{ integrations: Integration[] }>("/api/integrations");
  return payload.integrations;
}

export function configureOpenRouter(apiKey: string): Promise<{ connected: boolean; message: string }> {
  return request("/api/integrations/openrouter", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_key: apiKey }),
  });
}

export function configureBrightData(apiToken: string, enabled: boolean, maxRecordsPerRefresh: number): Promise<{ connected: boolean; enabled: boolean; max_records_per_refresh: number; message: string }> {
  return request("/api/integrations/bright-data", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ api_token: apiToken, enabled, max_records_per_refresh: maxRecordsPerRefresh }),
  });
}

export interface BrightDataEnrichment {
  requested: number;
  improved: number;
  no_change: number;
  failed: number;
  skipped_cached: number;
  salary_added: number;
  location_added: number;
  work_mode_added: number;
  apply_links_added: number;
  message: string;
}

export function enrichBrightData(): Promise<BrightDataEnrichment> {
  return request("/api/integrations/bright-data/enrich", { method: "POST" });
}

export function getGmailSetup(): Promise<GmailSetup> {
  return request("/api/integrations/gmail/setup");
}

export function beginGmailAuthorization(file: File): Promise<{ authorization_url: string }> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/integrations/gmail/authorize", { method: "POST", body });
}

export function startTelegramPairing(token: string): Promise<TelegramPairing> {
  return request("/api/integrations/telegram/pairing", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token }),
  });
}

export function getTelegramPairing(sessionId: string): Promise<TelegramPairing> {
  return request(`/api/integrations/telegram/pairing/${encodeURIComponent(sessionId)}`);
}

export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return request<OnboardingStatus>("/api/onboarding");
}

export function uploadResume(file: File): Promise<{ filename: string; registered_sources: number; added?: number; already_registered?: boolean }> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/career-material/resumes", { method: "POST", body });
}

export function skipOnboarding(): Promise<void> {
  return request("/api/onboarding/skip", { method: "POST" });
}

export function startOnboarding(useAi: boolean, apiKey = ""): Promise<OnboardingStatus> {
  return request("/api/onboarding/start", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ use_ai: useAi, api_key: apiKey }),
  });
}

export function answerOnboarding(
  step: string,
  answer: Record<string, unknown>,
): Promise<OnboardingStatus> {
  return request("/api/onboarding/answer", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ step, answer }),
  });
}

export function backOnboarding(): Promise<OnboardingStatus> {
  return request("/api/onboarding/back", { method: "POST" });
}

export function activateJobSearch(): Promise<OnboardingStatus> {
  return request("/api/job-search/activate", { method: "POST" });
}

export function getSearchPreferences(): Promise<SearchPreferences> {
  return request("/api/job-search/preferences");
}

export function saveSearchPreferences(preferences: SearchPreferences): Promise<SearchPreferences> {
  return request("/api/job-search/preferences", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(preferences),
  });
}

export function getResumes(): Promise<ResumeLibrary> { return request("/api/resumes"); }
export function restoreResume(resumeId: string): Promise<{ restored: boolean; message: string }> {
  return request("/api/resumes/restore", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ resume_id: resumeId }),
  });
}

export function getResumeRecommendation(jobId: string, signal?: AbortSignal): Promise<ResumeRecommendation> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/resume-recommendation`,
    signal ? { signal } : {},
    8_000,
    "Loading the resume recommendation took too long.",
  );
}
export function getJobScreenStatus(jobId: string, signal?: AbortSignal): Promise<JobScreenState> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/screen-status`,
    signal ? { signal } : {},
    8_000,
    "Checking the screen status took too long.",
  );
}
export function screenJob(jobId: string): Promise<JobScreenState> {
  return requestWithTimeout(
    `/api/jobs/${encodeURIComponent(jobId)}/screen`,
    { method: "POST" },
    10_000,
    "Starting the screen took too long. Check its status before trying again.",
  );
}

export function getBlockedCompanies(): Promise<{ companies: string[] }> { return request("/api/blocked-companies"); }
export function getJobFilterDefaults(): Promise<import("./types").ViewFilters> { return request("/api/job-filter-defaults"); }
export function setCompanyBlocked(company: string, blocked: boolean): Promise<{ companies: string[] }> {
  return requestWithTimeout("/api/blocked-companies", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ company, blocked }) }, 10_000, "Saving the company preference took too long. Please try again.");
}

export interface JobSourcesState {
  providers: { id: string; name: string; enabled: boolean; detail: string }[];
  scan: { status: string; message?: string; new_jobs?: number; errors?: { provider: string; message: string }[] };
}
export function getJobSources(): Promise<JobSourcesState> { return requestWithTimeout("/api/job-sources", {}, 8_000, "Loading job sources took too long."); }
export function setJobSource(id: string, enabled: boolean): Promise<JobSourcesState> {
  return requestWithTimeout(`/api/job-sources/${encodeURIComponent(id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) }, 10_000, "Saving the job source took too long. Please try again.");
}
export function startJobScan(): Promise<JobSourcesState> { return requestWithTimeout("/api/job-sources/scan", { method: "POST" }, 10_000, "Starting the job search took too long. Check its status before trying again."); }

export interface ScreeningBackfillState {
  status: "idle" | "running" | "complete" | "partial" | "failed";
  message: string;
  enabled: boolean;
  available: boolean;
  max_jobs: number;
  attempted_jobs?: number;
  screened_jobs?: number;
  batch_count?: number;
  pending_screening_jobs?: number;
  cached_jobs?: number;
  failed_jobs?: number;
  failure_categories?: Record<string, number>;
  provider_requests?: number;
  input_tokens?: number;
  output_tokens?: number;
  cost_usd?: string;
  duration_seconds?: number;
  average_seconds_per_attempt?: number;
  success_rate?: number;
  recommended_jobs?: number;
  needs_review_jobs?: number;
  started_at?: string;
  finished_at?: string;
}
export function getScreeningBackfill(): Promise<ScreeningBackfillState> { return requestWithTimeout("/api/jobs/screening-backfill", {}, 8_000, "Loading screening progress took too long."); }
export function startScreeningBackfill(): Promise<ScreeningBackfillState> { return requestWithTimeout("/api/jobs/screening-backfill", { method: "POST" }, 10_000, "Starting the screening backfill took too long. Check its status before trying again."); }

export interface ScrapeSchedule {
  configured: boolean;
  enabled: boolean;
  times: string[];
  timezone: string;
  next_run: string | null;
  last_run: string | null;
  service_status: "online" | "offline" | "unknown";
  screening_enabled: boolean;
  screening_max_jobs: number;
  screening_available: boolean;
  current_stage: "idle" | "searching" | "screening";
  recommendation_revision?: string;
}
export function getScrapeSchedule(): Promise<ScrapeSchedule> { return requestWithTimeout("/api/scrape-schedule", {}, 8_000, "Loading the schedule took too long."); }
export function saveScrapeSchedule(enabled: boolean, times: string[], screeningEnabled = false, screeningMaxJobs = 6): Promise<ScrapeSchedule> {
  return requestWithTimeout("/api/scrape-schedule", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled, times, screening_enabled: screeningEnabled, screening_max_jobs: screeningMaxJobs }) }, 10_000, "Saving the schedule took too long. Please try again.");
}

export function previewRoleTitles(scope: "onboarding" | "settings", titles: string[]): Promise<{ titles: string[]; remaining: number; minimum_length: number; maximum_length: number }> {
  return request("/api/job-search/roles/preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scope, titles }),
  });
}
