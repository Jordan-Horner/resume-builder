// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "./api";
import { JobsPage } from "./pages/JobsPage";
import { EMPTY_VIEW } from "./viewPreferences";
import type { Job } from "./types";

vi.mock("./api", () => ({
  getJobFilterDefaults: vi.fn(), getSearchPreferences: vi.fn(), getBlockedCompanies: vi.fn(),
  getJobs: vi.fn(), getResumeRecommendation: vi.fn(), markJobApplied: vi.fn(),
  markJobNotInterested: vi.fn(), setCompanyBlocked: vi.fn(), activateJobSearch: vi.fn(),
  getJobSources: vi.fn(), startJobScan: vi.fn(), estimateJobSalary: vi.fn(),
  getSavedJobSalary: vi.fn(),
  getSavedJobScreen: vi.fn(), screenJob: vi.fn(),
  getJobFeedback: vi.fn(), saveJobFeedback: vi.fn(), recordJobPostingOpened: vi.fn(),
  getScrapeSchedule: vi.fn(),
}));
const job: Job = { id: "one", title: "Support Engineer", company: "Example", location: "Remote", employment_type: "fulltime", salary_min: null, salary_max: null, salary_currency: null, salary_interval: null, posted_at: null, first_seen_at: null, description: "Support customers", work_modes: ["remote"], providers: [], url: null };
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(api.getJobFilterDefaults).mockResolvedValue(EMPTY_VIEW);
  vi.mocked(api.getSearchPreferences).mockResolvedValue({ status: "active", revision: "one", titles: [], country: "US", work_modes: ["remote"], onsite_locations: [], remote_location_terms: [], clearance_preference: "neutral", preferred_job_attributes: [], avoided_job_attributes: [], compensation: { skipped: true, minimum: null, target: null, currency: null, period: null } });
  vi.mocked(api.getBlockedCompanies).mockResolvedValue({ companies: [] });
  vi.mocked(api.getScrapeSchedule).mockResolvedValue({ configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York", next_run: null, last_run: null, service_status: "online", screening_enabled: true, screening_max_jobs: 15, screening_available: true, current_stage: "idle" });
  vi.mocked(api.getResumeRecommendation).mockResolvedValue({ status: "unavailable", recommended_resume: null, match: null, target: null, message: "None" });
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 1 });
  vi.mocked(api.markJobApplied).mockResolvedValue({});
  vi.mocked(api.getSavedJobSalary).mockResolvedValue(null);
  vi.mocked(api.getSavedJobScreen).mockResolvedValue(null);
  vi.mocked(api.getJobFeedback).mockResolvedValue({ job_id: "one", latest: null, personalization: { hot_label: "Learning your preferences", fit_score: 0.25, interest_score: 0.5, company_score: 0.5, fit_label: "Low", interest_label: "Neutral", company_label: "Neutral", confidence: "unknown", reasons: [], hot: false, hot_reasons: [] } });
  vi.mocked(api.saveJobFeedback).mockResolvedValue({ job_id: "one", latest: { action: "interested", reasons: [], created_at: "2026-09-06T12:00:00Z" }, personalization: { hot_label: "Low priority", fit_score: 0.25, interest_score: 0.85, company_score: 0.5, fit_label: "Low", interest_label: "High", company_label: "Neutral", confidence: "unknown", reasons: ["You marked this job positively."], hot: false, hot_reasons: [] } });
  vi.mocked(api.recordJobPostingOpened).mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
async function click(text: string) {
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === text)?.click());
}
async function clickSalaryEstimate() {
  await act(async () => (host.querySelector(".estimate-salary-button") as HTMLButtonElement)?.click());
}
async function openJob() {
  await act(async () => root.render(<JobsPage />));
  await act(async () => (host.querySelector(".job-row") as HTMLButtonElement).click());
}
it.each(["Mark as applied", "Not interested"])("refreshes the final-job state after %s", async (action) => {
  await openJob();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 0 });
  await click(action);
  expect(host.textContent).toContain("Build your job queue");
  expect(host.textContent).not.toContain("hidden by your current filters");
  expect(api.getJobFilterDefaults).toHaveBeenCalledTimes(1);
});
it("refills the page from the backend after removing a result", async () => {
  await openJob();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [{ ...job, id: "two", title: "Platform Engineer" }], count: 101, reviewable_count: 101 });
  await click("Not interested");
  expect(host.textContent).toContain("Platform Engineer");
  expect(host.textContent).toContain("101 jobs to review");
  expect(document.activeElement).toBe(host.querySelector(".job-row"));
});

it("records interested feedback without asking the user to classify it", async () => {
  await openJob();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 1 });
  await click("Interested");

  expect(api.saveJobFeedback).toHaveBeenCalledWith("one", "interested", []);
  expect(host.textContent).not.toContain("What stands out?");
  expect(host.textContent).toContain("saved to Interested jobs");
  expect(host.querySelector(".job-detail")).toBeNull();
});

it("shows completed quick-screen metadata in the queue", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, quick_screen: { status: "complete", label: "Strong", resume_name: "Support Engineer", generated_at: "2026-09-06T12:00:00Z" } }],
    count: 1,
    reviewable_count: 1,
  });

  await act(async () => root.render(<JobsPage />));

  expect(host.querySelector(".job-screen-status")?.textContent).toContain("Strong · Support Engineer");
});

it("requests the backend-owned recommendation queue without hiding the full inventory", async () => {
  vi.mocked(api.getJobs).mockResolvedValueOnce({ jobs: [job], count: 1, reviewable_count: 2 });
  await act(async () => root.render(<JobsPage />));
  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "recommended");
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 2 });
  await click("All jobs");
  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "all");
});

it("keeps explicitly interested jobs in their own queue", async () => {
  await act(async () => root.render(<JobsPage />));
  await click("Interested jobs");

  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "interested");
});

it("reuses a loaded queue when switching back to it", async () => {
  const allJob = { ...job, id: "two", title: "Platform Engineer" };
  vi.mocked(api.getJobs).mockImplementation(async (_filters, queue) => ({
    jobs: queue === "all" ? [allJob] : [job],
    count: 1,
    reviewable_count: 2,
  }));
  await act(async () => root.render(<JobsPage />));

  await click("All jobs");
  expect(host.textContent).toContain("Platform Engineer");
  await click("Recommended Jobs");

  expect(host.textContent).toContain("Support Engineer");
  expect(api.getJobs).toHaveBeenCalledTimes(2);
});

it("shows when the scheduled search is still preparing recommendations", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 12 });
  vi.mocked(api.getScrapeSchedule).mockResolvedValue({ configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York", next_run: null, last_run: null, service_status: "online", screening_enabled: true, screening_max_jobs: 15, screening_available: true, current_stage: "searching" });

  await act(async () => root.render(<JobsPage />));

  expect(host.textContent).toContain("Finding new jobs…");
  expect(host.textContent).toContain("screened automatically before they appear here");
});

it("describes a failed automatic screen as unavailable, not as a fit judgment", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, quick_screen: { status: "failed", label: "Screen unavailable", resume_name: null, generated_at: null } }],
    count: 1,
    reviewable_count: 1,
  });

  await act(async () => root.render(<JobsPage />));

  expect(host.querySelector(".job-screen-status")?.textContent).toBe("Screen unavailable");
  expect(host.textContent).not.toContain("Screen failed");
});

it("records opening the original posting as a passive positive signal", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [{ ...job, url: "https://example.com/job" }], count: 1, reviewable_count: 1 });
  await openJob();

  await act(async () => (host.querySelector(".original-link") as HTMLAnchorElement).click());

  expect(api.recordJobPostingOpened).toHaveBeenCalledWith("one");
});

it("returns focus to the selected job when details close", async () => {
  await openJob();
  const row = host.querySelector(".job-row");

  await act(async () => (host.querySelector('[aria-label="Close job details"]') as HTMLButtonElement).click());
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  expect(document.activeElement).toBe(row);
});
it("temporarily filters clearance jobs without changing saved preferences", async () => {
  await act(async () => root.render(<JobsPage />));
  const filter = host.querySelector(".clearance-filter") as HTMLSelectElement;

  expect(filter.value).toBe("all");

  await act(async () => {
    filter.value = "only";
    filter.dispatchEvent(new Event("change", { bubbles: true }));
  });

  expect(api.getJobs).toHaveBeenLastCalledWith(
    expect.objectContaining({
      view: expect.objectContaining({ clearanceMode: "only" }),
    }),
    "recommended",
  );
});
it("retries a failed refresh without repeating the successful mutation", async () => {
  await openJob();
  vi.mocked(api.getJobs).mockRejectedValueOnce(new Error("Queue unavailable"));
  await click("Mark as applied");
  expect(host.textContent).toContain("moved to Applications");
  expect(host.textContent).toContain("Queue unavailable");
  expect(host.querySelector(".job-row")).toBeNull();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 0 });
  await click("Try again");
  expect(api.markJobApplied).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Build your job queue");
});

it("offers salary estimation only inside the opened job description", async () => {
  await act(async () => root.render(<JobsPage />));
  expect(host.textContent).not.toContain("Estimate Salary");
  expect(api.estimateJobSalary).not.toHaveBeenCalled();
  await act(async () => (host.querySelector(".job-row") as HTMLButtonElement).click());
  expect(host.querySelector(".job-detail .detail-tags")?.textContent).toContain("Estimate Salary");
  expect(api.estimateJobSalary).not.toHaveBeenCalled();
});

it("screens a job only after the user requests it", async () => {
  const result = { status: "complete" as const, cached: false, result: {
    job_id: "one", fit: "good_match", fit_label: "Good fit", screening_label: "Quick screen" as const, eligibility: "eligible",
    eligibility_label: "Eligible", recommendation: "pursue", recommendation_label: "Pursue",
    confidence: "medium" as const, strengths: [], gaps: [], unknowns: [], stretch_case: null,
    reasoning_summary: "Strong production support evidence.",
    preference_fit: { label: "Looks aligned" as const, matches: [{ preference: "Production ownership", direction: "prefer" as const, outcome: "match" as const, explanation: "The role owns production incidents.", posting_evidence: "production support" }], conflicts: [], unknown_count: 1 },
    evidence_coverage: "good" as const, evidence_strategy: "criterion-driven" as const,
    criterion_evidence: [{ criterion_id: "incident-response", label: "Incident response", importance: "required" as const, status: "demonstrated-candidate" as const, fact_ids: ["OPS-001"] }],
    criterion_assessments: [{ criterion_id: "incident-response", outcome: "supported" as const, confidence: "high" as const, fact_ids: ["OPS-001"], explanation: "Verified incident leadership directly supports this requirement.", materially_affects_recommendation: true }],
    resume_match: { resume_id: "resumes/baselines/support.md", name: "Production Support Engineer", sha256: "a".repeat(64), label: "Strong match" as const, strongest_overlap: ["Incident response"], primary_gap: null, alternative: null },
    posting_coverage: "complete" as const, evidence_used: [{
      fact_id: "OPS-001", title: "Production incident response", category: "employment" as const, strength: "demonstrated" as const,
    }],
  } };
  vi.mocked(api.screenJob).mockResolvedValue(result);
  await openJob();
  expect(api.screenJob).not.toHaveBeenCalled();

  await click("Screen job");

  expect(api.screenJob).toHaveBeenCalledWith("one");
  expect(host.textContent).toContain("Good fit");
  expect(host.textContent).toContain("Strong production support evidence.");
  expect(host.textContent).toContain("Based on 1 verified career fact.");
  expect(host.textContent).toContain("Incident response: Supported");
  expect(host.textContent).toContain("Resume matchStrong matchProduction Support Engineer");
  expect(host.textContent).toContain("Strongest overlap: Incident response");
  expect(host.querySelector<HTMLAnchorElement>('.job-resume-match a')?.getAttribute("href")).toContain("resumes%2Fbaselines%2Fsupport.md");
  expect(host.textContent).toContain("Verified incident leadership directly supports this requirement.");
  expect(host.textContent).toContain("What you wantLooks aligned");
  expect(host.textContent).toContain("Matches: The role owns production incidents.");
  expect(host.textContent).toContain("1 saved preference was not clear from this posting.");
  expect(host.textContent).toContain("Evidence used");
});

it("keeps screening state and late results attached to the job that started them", async () => {
  let resolveFirst!: (value: Awaited<ReturnType<typeof api.screenJob>>) => void;
  const secondJob = { ...job, id: "two", title: "Platform Engineer" };
  const screenResult = (jobId: string, fitLabel: string): Awaited<ReturnType<typeof api.screenJob>> => ({
    status: "complete" as const,
    cached: false,
    result: {
      job_id: jobId,
      fit: "good_match",
      fit_label: fitLabel,
      screening_label: "Quick screen" as const,
      eligibility: "eligible",
      eligibility_label: "Eligible",
      recommendation: "pursue",
      recommendation_label: "Pursue",
      confidence: "medium" as const,
      strengths: [],
      gaps: [],
      unknowns: [],
      stretch_case: null,
      reasoning_summary: `${fitLabel} evidence.`,
      preference_fit: { label: "No job preferences saved" as const, matches: [], conflicts: [], unknown_count: 0 },
      evidence_coverage: "good" as const,
      evidence_strategy: "posting-wide",
      criterion_evidence: undefined,
      criterion_assessments: undefined,
      posting_coverage: "complete" as const,
      evidence_used: [],
    },
  });
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job, secondJob], count: 2, reviewable_count: 2 });
  vi.mocked(api.screenJob).mockImplementation((jobId) => jobId === "one"
    ? new Promise((resolve) => { resolveFirst = resolve; })
    : Promise.resolve(screenResult("two", "Platform fit")));

  await openJob();
  await click("Screen job");
  expect(host.textContent).toContain("Screening job…");

  await act(async () => (host.querySelectorAll(".job-row")[1] as HTMLButtonElement).click());
  expect(host.textContent).toContain("Screen job");
  expect(host.textContent).not.toContain("Screening job…");

  await click("Screen job");
  expect(api.screenJob).toHaveBeenNthCalledWith(2, "two");
  expect(host.textContent).toContain("Platform fit");

  await act(async () => resolveFirst(screenResult("one", "Support fit")));
  expect(host.textContent).toContain("Platform fit");
  expect(host.textContent).not.toContain("Support fit");
});

it.each([{ salary_min: 80000, salary_max: null }, { salary_min: null, salary_max: 100000 }])("keeps posted partial pay instead of offering an estimate: %j", async (pay) => {
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [{ ...job, ...pay }], count: 1, reviewable_count: 1 });
  await openJob();
  expect(host.textContent).not.toContain("Estimate Salary");
  expect(api.estimateJobSalary).not.toHaveBeenCalled();
});

const estimatedSalary = {
  status: "estimated" as const, job_id: "one", cached: false, posted_salary: null,
  estimate: { status: "estimated" as const, minimum: 80000, maximum: 110000, currency: "USD", period: "year" as const, confidence: "low" as const, reasoning: "Based on similar support roles.", company_basis: "Company pay policy unknown.", assumptions: ["Base salary only."], related_job_ids: [] },
};

it("requests salary on click, prevents duplicates and labels the result as estimated", async () => {
  let resolve!: (value: typeof estimatedSalary) => void;
  vi.mocked(api.estimateJobSalary).mockImplementation(() => new Promise((done) => { resolve = done; }));
  await openJob();
  await clickSalaryEstimate();
  expect(api.estimateJobSalary).toHaveBeenCalledWith("one");
  const pending = host.querySelector(".estimate-salary-button") as HTMLButtonElement;
  expect(pending.disabled).toBe(true);
  await act(async () => pending.click());
  expect(api.estimateJobSalary).toHaveBeenCalledTimes(1);
  await act(async () => resolve(estimatedSalary));
  expect(host.querySelector(".job-detail")?.textContent).toContain("Est. $80K–$110K / year");
  expect(host.textContent).toContain("Not employer-confirmed");
  expect(host.textContent).toContain("Low confidence");
  expect(job.salary_min).toBeNull();
});

it("restores a saved salary estimate after closing and reopening the job", async () => {
  vi.mocked(api.estimateJobSalary).mockResolvedValue(estimatedSalary);
  await openJob();
  await clickSalaryEstimate();
  expect(host.querySelector(".job-detail")?.textContent).toContain("Est. $80K–$110K / year");
  vi.mocked(api.getSavedJobSalary).mockResolvedValue({ ...estimatedSalary, cached: true });
  await act(async () => (host.querySelector('[aria-label="Close job details"]') as HTMLButtonElement).click());
  await act(async () => (host.querySelector(".job-row") as HTMLButtonElement).click());
  expect(host.querySelector(".job-detail")?.textContent).toContain("Est. $80K–$110K / year");
  expect(api.estimateJobSalary).toHaveBeenCalledTimes(1);
});

it("keeps an in-progress salary estimate running when the job is closed and reopened", async () => {
  let resolve!: (value: typeof estimatedSalary) => void;
  vi.mocked(api.estimateJobSalary).mockImplementation(() => new Promise((done) => { resolve = done; }));
  await openJob();
  await clickSalaryEstimate();
  await act(async () => (host.querySelector('[aria-label="Close job details"]') as HTMLButtonElement).click());
  await act(async () => (host.querySelector(".job-row") as HTMLButtonElement).click());
  const pending = host.querySelector(".estimate-salary-button") as HTMLButtonElement;
  expect(pending.disabled).toBe(true);
  expect(pending.textContent).toContain("Estimating…");
  await act(async () => resolve(estimatedSalary));
  expect(host.querySelector(".job-detail")?.textContent).toContain("Est. $80K–$110K / year");
  expect(api.estimateJobSalary).toHaveBeenCalledTimes(1);
});

it("shows provider errors and supports retry", async () => {
  vi.mocked(api.estimateJobSalary).mockRejectedValueOnce(new Error("Configure an AI provider in Settings."));
  await openJob();
  await clickSalaryEstimate();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("Configure an AI provider");
  vi.mocked(api.estimateJobSalary).mockResolvedValue(estimatedSalary);
  await clickSalaryEstimate();
  expect(host.textContent).toContain("Est. $80K–$110K / year");
});

it("explains unavailable estimates", async () => {
  vi.mocked(api.estimateJobSalary).mockResolvedValue({ status: "unavailable", job_id: "one", cached: false, posted_salary: null, estimate: null });
  await openJob();
  await clickSalaryEstimate();
  expect(host.textContent).toContain("Estimate unavailable");
  expect(host.textContent).toContain("enough information");
});

it("does not show a late estimate on a different job", async () => {
  let resolve!: (value: typeof estimatedSalary) => void;
  vi.mocked(api.estimateJobSalary).mockImplementation(() => new Promise((done) => { resolve = done; }));
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job, { ...job, id: "two", title: "Another job" }], count: 2, reviewable_count: 2 });
  await openJob();
  await clickSalaryEstimate();
  await act(async () => (host.querySelectorAll(".job-row")[1] as HTMLButtonElement).click());
  await act(async () => resolve(estimatedSalary));
  expect(host.querySelector(".job-detail")?.textContent).not.toContain("Est. $");
  expect(host.querySelector(".job-detail")?.textContent).toContain("Estimate Salary");
});
