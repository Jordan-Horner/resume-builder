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
  vi.mocked(api.getSearchPreferences).mockResolvedValue({ status: "active", revision: "one", titles: [], skill_terms: [], country: "US", work_modes: ["remote"], onsite_locations: [], remote_location_terms: [], clearance_preference: "neutral", compensation: { skipped: true, minimum: null, target: null, currency: null, period: null } });
  vi.mocked(api.getBlockedCompanies).mockResolvedValue({ companies: [] });
  vi.mocked(api.getResumeRecommendation).mockResolvedValue({ status: "unavailable", recommended_resume: null, match: null, target: null, message: "None" });
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 1 });
  vi.mocked(api.markJobApplied).mockResolvedValue({});
  vi.mocked(api.markJobNotInterested).mockResolvedValue(undefined);
  vi.mocked(api.getSavedJobSalary).mockResolvedValue(null);
  vi.mocked(api.getSavedJobScreen).mockResolvedValue(null);
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
});
it("temporarily hides clearance jobs without changing saved preferences", async () => {
  await act(async () => root.render(<JobsPage />));
  const toggle = host.querySelector(".clearance-filter input") as HTMLInputElement;

  await act(async () => toggle.click());

  expect(api.getJobs).toHaveBeenLastCalledWith(
    expect.objectContaining({
      view: expect.objectContaining({ includeClearanceJobs: false }),
    }),
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
    job_id: "one", fit: "good_match", fit_label: "Good fit", eligibility: "eligible",
    eligibility_label: "Eligible", recommendation: "pursue", recommendation_label: "Pursue",
    confidence: "medium" as const, strengths: [], gaps: [], unknowns: [], stretch_case: null,
    reasoning_summary: "Strong production support evidence.",
  } };
  vi.mocked(api.screenJob).mockResolvedValue(result);
  await openJob();
  expect(api.screenJob).not.toHaveBeenCalled();

  await click("Screen job");

  expect(api.screenJob).toHaveBeenCalledWith("one");
  expect(host.textContent).toContain("Good fit");
  expect(host.textContent).toContain("Strong production support evidence.");
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
