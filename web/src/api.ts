import type { Application, Integration, Job, JobFilters, OnboardingStatus, SearchPreferences } from "./types";

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
  id: "portal" | "scheduler" | "telegram";
  name: string;
  status: "online" | "offline" | "disabled" | "not_configured" | "error" | "unknown";
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

export async function getJobs(filters: JobFilters): Promise<{ jobs: Job[]; count: number; reviewable_count: number }> {
  const params = new URLSearchParams();
  if (filters.view) params.set("view_filters", JSON.stringify({ ...filters.view, roles: [], locations: filters.view.locations.map((item) => item.trim()).filter(Boolean) }));
  if (filters.search.trim()) params.set("search", filters.search.trim());
  if (filters.workMode) params.set("work_mode", filters.workMode);
  if (filters.dateDays) params.set("date_days", String(filters.dateDays));
  if (filters.employmentType) params.set("employment_type", filters.employmentType);
  return request<{ jobs: Job[]; count: number; reviewable_count: number }>(`/api/jobs?${params.toString()}`);
}

export function markJobNotInterested(jobId: string): Promise<void> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/not-interested`, { method: "POST" });
}

export function markJobApplied(jobId: string): Promise<unknown> {
  return request(`/api/jobs/${encodeURIComponent(jobId)}/applied`, { method: "POST" });
}

export async function getApplications(): Promise<Application[]> {
  const payload = await request<{ applications: Application[] }>("/api/applications");
  return payload.applications;
}

export async function getIntegrations(): Promise<Integration[]> {
  const payload = await request<{ integrations: Integration[] }>("/api/integrations");
  return payload.integrations;
}

export function getOnboardingStatus(): Promise<OnboardingStatus> {
  return request<OnboardingStatus>("/api/onboarding");
}

export function uploadResume(file: File): Promise<{ filename: string; registered_sources: number }> {
  const body = new FormData();
  body.append("file", file);
  return request("/api/onboarding/resume", { method: "POST", body });
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

export function getBlockedCompanies(): Promise<{ companies: string[] }> { return request("/api/blocked-companies"); }
export function getJobFilterDefaults(): Promise<import("./types").ViewFilters> { return request("/api/job-filter-defaults"); }
export function setCompanyBlocked(company: string, blocked: boolean): Promise<{ companies: string[] }> {
  return request("/api/blocked-companies", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ company, blocked }) });
}

export interface JobSourcesState {
  providers: { id: string; name: string; enabled: boolean; detail: string }[];
  scan: { status: string; message?: string; new_jobs?: number; errors?: { provider: string; message: string }[] };
}
export function getJobSources(): Promise<JobSourcesState> { return request("/api/job-sources"); }
export function setJobSource(id: string, enabled: boolean): Promise<JobSourcesState> {
  return request(`/api/job-sources/${encodeURIComponent(id)}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }) });
}
export function startJobScan(): Promise<JobSourcesState> { return request("/api/job-sources/scan", { method: "POST" }); }

export interface ScrapeSchedule {
  configured: boolean;
  enabled: boolean;
  times: string[];
  timezone: string;
  next_run: string | null;
  last_run: string | null;
  service_status: "online" | "offline" | "unknown";
}
export function getScrapeSchedule(): Promise<ScrapeSchedule> { return request("/api/scrape-schedule"); }
export function saveScrapeSchedule(enabled: boolean, times: string[]): Promise<ScrapeSchedule> {
  return request("/api/scrape-schedule", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled, times }) });
}
