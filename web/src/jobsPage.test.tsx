// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import * as api from "./api";
import { JobsPage } from "./pages/JobsPage";
import { EMPTY_VIEW } from "./viewPreferences";
import { __resetJobDetailCaches } from "./jobs/JobDetailPanel";
import type { Job } from "./types";

vi.mock("./api", () => ({
  getJobFilterDefaults: vi.fn(), getSearchPreferences: vi.fn(), getBlockedCompanies: vi.fn(), getJob: vi.fn(),
  getJobs: vi.fn(), getResumeRecommendation: vi.fn(), markJobApplied: vi.fn(),
  hideJobPosting: vi.fn(), markJobNotInterested: vi.fn(), setCompanyBlocked: vi.fn(), activateJobSearch: vi.fn(),
  getJobSources: vi.fn(), startJobScan: vi.fn(), estimateJobSalary: vi.fn(),
  getSavedJobSalary: vi.fn(),
  getJobScreenStatus: vi.fn(), screenJob: vi.fn(),
  getJobFeedback: vi.fn(), saveJobFeedback: vi.fn(), recordJobPostingOpened: vi.fn(),
  getScrapeSchedule: vi.fn(),
}));
const job: Job = { id: "one", title: "Support Engineer", company: "Example", location: "Remote", employment_type: "fulltime", salary_min: null, salary_max: null, salary_currency: null, salary_interval: null, posted_at: null, first_seen_at: null, description: "Support customers", work_modes: ["remote"], providers: [], url: null };
let root: Root;
let host: HTMLDivElement;
beforeEach(() => {
  vi.resetAllMocks();
  localStorage.clear();
  __resetJobDetailCaches();
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(api.getJobFilterDefaults).mockResolvedValue(EMPTY_VIEW);
  vi.mocked(api.getSearchPreferences).mockResolvedValue({ status: "active", revision: "one", titles: [], country: "US", work_modes: ["remote"], onsite_locations: [], remote_location_terms: [], clearance_preference: "neutral", preferred_job_attributes: [], avoided_job_attributes: [], compensation: { skipped: true, minimum: null, target: null, currency: null, period: null } });
  vi.mocked(api.getBlockedCompanies).mockResolvedValue({ companies: [] });
  vi.mocked(api.getJob).mockResolvedValue(job);
  vi.mocked(api.getScrapeSchedule).mockResolvedValue({ configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York", next_run: null, last_run: null, service_status: "online", screening_enabled: true, screening_max_jobs: 15, screening_available: true, current_stage: "idle" });
  vi.mocked(api.getResumeRecommendation).mockResolvedValue({ status: "unavailable", recommended_resume: null, available_resumes: [], match: null, target: null, message: "None" });
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 1 });
  vi.mocked(api.markJobApplied).mockResolvedValue({});
  vi.mocked(api.hideJobPosting).mockResolvedValue({ job_id: "one", reason: "closed", personalization_updated: false });
  vi.mocked(api.getSavedJobSalary).mockResolvedValue(null);
  vi.mocked(api.getJobScreenStatus).mockResolvedValue({ status: "idle", job_id: "one" });
  vi.mocked(api.getJobFeedback).mockResolvedValue({ job_id: "one", latest: null, personalization: { hot_label: "Learning your preferences", fit_score: 0.25, interest_score: 0.5, company_score: 0.5, fit_label: "Low", interest_label: "Neutral", company_label: "Neutral", confidence: "unknown", reasons: [], hot: false, hot_reasons: [] } });
  vi.mocked(api.saveJobFeedback).mockResolvedValue({ job_id: "one", latest: { action: "interested", reasons: [], created_at: "2026-09-06T12:00:00Z" }, personalization: { hot_label: "Low priority", fit_score: 0.25, interest_score: 0.85, company_score: 0.5, fit_label: "Low", interest_label: "High", company_label: "Neutral", confidence: "unknown", reasons: ["You marked this job positively."], hot: false, hot_reasons: [] } });
  vi.mocked(api.recordJobPostingOpened).mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks(); });
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
async function hidePosting(reason = "Posting is closed") {
  await click("Hide posting");
  await click(reason);
}
it.each(["applied", "hidden"])("refreshes the final-job state after a job is %s", async (action) => {
  await openJob();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 0 });
  if (action === "applied") await click("Mark as applied");
  else await hidePosting();
  expect(host.textContent).toContain("Build your job queue");
  expect(host.textContent).not.toContain("hidden by your current filters");
  expect(api.getJobFilterDefaults).toHaveBeenCalledTimes(1);
});
it("refills the page from the backend after removing a result", async () => {
  await openJob();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [{ ...job, id: "two", title: "Platform Engineer" }], count: 101, reviewable_count: 101 });
  await hidePosting();
  expect(host.textContent).toContain("Platform Engineer");
  expect(host.textContent).toContain("101 jobs to review");
  expect(document.activeElement).toBe(host.querySelector(".job-row"));
});

it("keeps remaining jobs visible while refreshing after a dismissal", async () => {
  const remainingJob = { ...job, id: "two", title: "Platform Engineer" };
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job, remainingJob], count: 2, reviewable_count: 2 });
  await openJob();
  let finishRefresh!: (payload: { jobs: Job[]; count: number; reviewable_count: number }) => void;
  vi.mocked(api.getJobs).mockImplementationOnce(() => new Promise((resolve) => { finishRefresh = resolve; }));

  await hidePosting();

  expect(host.textContent).toContain("Platform Engineer");
  expect([...host.querySelectorAll(".job-row")].some((row) => row.textContent?.includes("Support Engineer"))).toBe(false);
  expect(host.querySelector(".loading-rows")).toBeNull();
  await act(async () => finishRefresh({ jobs: [remainingJob], count: 1, reviewable_count: 1 }));
});

it("keeps unavailable-posting cleanup out of recommendation feedback", async () => {
  await openJob();

  await click("Hide posting");

  expect(host.textContent).toContain("Only “Not interested” changes future recommendations.");
  await click("Posting is closed");
  expect(api.hideJobPosting).toHaveBeenCalledWith("one", "closed");
  expect(api.saveJobFeedback).not.toHaveBeenCalledWith("one", "not_interested", []);
  expect(host.textContent).toContain("Similar roles will still be recommended");
});

it("labels an explicit fit rejection as recommendation feedback", async () => {
  vi.mocked(api.hideJobPosting).mockResolvedValue({ job_id: "one", reason: "not_relevant", personalization_updated: true });
  await openJob();

  await hidePosting("Not interested");

  expect(api.hideJobPosting).toHaveBeenCalledWith("one", "not_relevant");
  expect(host.textContent).toContain("Recommendations will use this feedback");
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

it("shows Hot without exposing screening metadata in the queue", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, personalization: { hot: true, hot_reasons: ["career_fit"], hot_score: 0.9 }, quick_screen: { status: "complete", label: "Strong", resume_name: "Support Engineer", generated_at: "2026-09-06T12:00:00Z" } }],
    count: 1,
    reviewable_count: 1,
  });

  await act(async () => root.render(<JobsPage />));

  expect(host.querySelector(".job-hot-status")?.textContent).toBe("Hot");
  expect(host.querySelector(".job-screen-state")).toBeNull();
  expect(host.textContent).not.toContain("Screened");
  expect(host.textContent).not.toContain("Support Engineer · Support Engineer");
});

it("shows backend-provided employer recognition in the row and job details", async () => {
  const recognizedJob: Job = {
    ...job,
    company_recognition: {
      major_employer: true,
      top_workplace: true,
      sources: ["fortune-500-2026", "great-place-to-work-2026"],
    },
  };
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [recognizedJob], count: 1, reviewable_count: 1 });
  vi.mocked(api.getJob).mockResolvedValue(recognizedJob);

  await openJob();

  expect(host.querySelector(".job-row .top-workplace")?.textContent).toBe("Top workplace");
  expect(host.querySelector(".job-row .major-employer")?.textContent).toBe("Major employer");
  expect(host.querySelector(".job-detail .top-workplace")?.textContent).toBe("Top workplace");
  expect(host.querySelector(".job-detail .major-employer")?.textContent).toBe("Major employer");
});

it("does not label a recommended job Hot without a completed Strong fit", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, personalization: { hot: false, hot_reasons: [], hot_score: 0.7 }, quick_screen: { status: "complete", label: "Good", resume_name: "Support Engineer", generated_at: "2026-09-06T12:00:00Z" } }],
    count: 1,
    reviewable_count: 1,
  });

  await act(async () => root.render(<JobsPage />));

  expect(host.querySelector(".job-hot-status")).toBeNull();
  expect(host.textContent).not.toContain("Screened");
});

it("requests the backend-owned recommendation queue without hiding the full inventory", async () => {
  vi.mocked(api.getJobs).mockResolvedValueOnce({ jobs: [job], count: 1, reviewable_count: 2 });
  await act(async () => root.render(<JobsPage />));
  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "recommended", expect.any(AbortSignal));
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 2 });
  await click("All jobs");
  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "all", expect.any(AbortSignal));
});

it("keeps explicitly interested jobs in their own queue", async () => {
  await act(async () => root.render(<JobsPage />));
  await click("Interested jobs");

  expect(api.getJobs).toHaveBeenLastCalledWith(expect.any(Object), "interested", expect.any(AbortSignal));
});

it("closes the open job details when switching queues", async () => {
  await openJob();

  expect(host.querySelector(".job-detail")).not.toBeNull();
  await click("All jobs");

  expect(host.querySelector(".job-detail")).toBeNull();
});

it("supports arrow-key navigation across the job queues", async () => {
  await act(async () => root.render(<JobsPage />));
  const recommended = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((tab) => tab.textContent === "Recommended Jobs")!;
  const interested = [...host.querySelectorAll<HTMLButtonElement>('[role="tab"]')].find((tab) => tab.textContent === "Interested jobs")!;

  await act(async () => {
    recommended.focus();
    recommended.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
  });

  expect(document.activeElement).toBe(interested);
  expect(interested.getAttribute("aria-selected")).toBe("true");
  expect(interested.tabIndex).toBe(0);
  expect(recommended.tabIndex).toBe(-1);
});

it("names the clearance filter independently from the All jobs queue", async () => {
  await act(async () => root.render(<JobsPage />));

  expect((host.querySelector('.clearance-filter option[value="all"]') as HTMLOptionElement).textContent).toBe("Any clearance");
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
  expect(host.textContent).toContain("New matches will be screened automatically");
});

it("explains that a restored text search is hiding jobs even while discovery runs", async () => {
  localStorage.setItem("resume-builder.job-view.v8", JSON.stringify({
    filters: { search: "wordbricks", dateDays: 0, workMode: "", employmentType: "", view: EMPTY_VIEW },
    previous: EMPTY_VIEW,
  }));
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 12 });
  vi.mocked(api.getScrapeSchedule).mockResolvedValue({ configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York", next_run: null, last_run: null, service_status: "online", screening_enabled: true, screening_max_jobs: 15, screening_available: true, current_stage: "searching" });

  await act(async () => root.render(<JobsPage />));
  await act(async () => { await new Promise((resolve) => window.setTimeout(resolve, 300)); });

  expect(host.textContent).toContain("No jobs match “wordbricks”");
  expect(host.textContent).toContain("Your saved search is still active");
  expect(host.textContent).not.toContain("Finding new jobs…");
  await click("Clear search");
  expect((host.querySelector('input[type="search"]') as HTMLInputElement).value).toBe("");
});

it("keeps failed automatic-screen metadata out of the queue", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, quick_screen: { status: "failed", label: "Screen unavailable", resume_name: null, generated_at: null } }],
    count: 1,
    reviewable_count: 1,
  });

  await act(async () => root.render(<JobsPage />));

  expect(host.querySelector(".job-screen-state")).toBeNull();
  expect(host.textContent).not.toContain("Screen failed");
});

it("does not call a completed background screen unscreened in job details", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({
    jobs: [{ ...job, quick_screen: { status: "complete", label: "Unknown", resume_name: "Support Engineer", generated_at: "2026-09-06T12:00:00Z" } }],
    count: 1,
    reviewable_count: 1,
  });

  await openJob();

  expect(host.textContent).toContain("Quick screen complete");
  expect(host.textContent).not.toContain("Refresh screen");
  expect(host.textContent).not.toContain("Not screened yet");
});

it("loads the full description only after a queue row is opened", async () => {
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [{ ...job, description: undefined }], count: 1, reviewable_count: 1 });

  await openJob();

  expect(api.getJob).toHaveBeenCalledWith("one", expect.any(AbortSignal));
  expect(host.textContent).toContain("Support customers");
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
    expect.any(AbortSignal),
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

it("requires and records the resume used when no single resume was recommended", async () => {
  vi.mocked(api.getResumeRecommendation).mockResolvedValue({
    status: "unavailable",
    recommended_resume: null,
    available_resumes: [
      { id: "resumes/baselines/devops.md", name: "DevOps", kind: "directional" },
      { id: "resumes/baselines/support.md", name: "Support", kind: "directional" },
    ],
    match: null,
    target: null,
    message: "Choose the resume you used.",
  });
  await openJob();

  const apply = [...host.querySelectorAll("button")].find((button) => button.textContent === "Choose resume first") as HTMLButtonElement;
  expect(apply.disabled).toBe(true);
  const select = host.querySelector(".resume-choice select") as HTMLSelectElement;
  await act(async () => {
    select.value = "resumes/baselines/devops.md";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  await click("Mark as applied");

  expect(api.markJobApplied).toHaveBeenCalledWith("one", "resumes/baselines/devops.md");
  expect(host.textContent).toContain("moved to Applications");
});

it("automatically clears action confirmations after eight seconds", async () => {
  await openJob();
  vi.useFakeTimers();
  await click("Mark as applied");

  expect(host.textContent).toContain("moved to Applications");
  await act(async () => vi.advanceTimersByTime(8000));
  expect(host.textContent).not.toContain("moved to Applications");
});

it("lets the user dismiss an action confirmation immediately", async () => {
  await openJob();
  await click("Mark as applied");

  await act(async () => (host.querySelector('[aria-label="Dismiss notification"]') as HTMLButtonElement).click());
  expect(host.textContent).not.toContain("moved to Applications");
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
    confidence: "medium" as const, strengths: [], gaps: [], unknowns: [],
    reasoning_summary: "Strong production support evidence.",
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
  expect(host.querySelector<HTMLDetailsElement>(".job-screen-rationale")?.open).toBe(false);
  expect(host.querySelectorAll(".job-fit-result")[0]?.textContent).toContain("Career fitGood fit");
  expect(host.querySelectorAll(".job-fit-result")[1]?.textContent).toContain("Resume matchStrong match");
  expect(host.querySelector(".job-screen-coverage")?.textContent).toContain("1Verified fact");
  expect(host.querySelector(".job-screen-coverage")?.textContent).toContain("1Criterion checked");
  expect(host.textContent).toContain("Incident response: Supported");
  expect(host.querySelector(".job-resume-match > a")?.textContent).toBe("Production Support Engineer");
  expect(host.querySelector(".job-resume-match > strong")?.textContent).toBe("Strong match");
  expect(host.querySelector(".job-resume-signals dd")?.textContent).toBe("Incident response");
  expect(host.querySelector<HTMLAnchorElement>('.job-resume-match a')?.getAttribute("href")).toContain("resumes%2Fbaselines%2Fsupport.md");
  expect(host.textContent).toContain("Verified incident leadership directly supports this requirement.");
  expect(host.textContent).toContain("Evidence used");
});

it("aligns career fit with vault-backed resume guidance", async () => {
  vi.mocked(api.getJobScreenStatus).mockResolvedValue({ status: "complete", cached: true, result: {
    job_id: "one", fit: "strong_match", fit_label: "Strong fit", screening_label: "Quick screen", eligibility: "eligible",
    eligibility_label: "Eligible", recommendation: "pursue", recommendation_label: "Pursue", confidence: "high",
    strengths: [], gaps: [], unknowns: [], reasoning_summary: "Strong infrastructure evidence.",
    evidence_coverage: "good", evidence_strategy: "posting-wide", posting_coverage: "complete",
    evidence_used: [{ fact_id: "OPS-001", title: "Infrastructure operations", category: "employment", strength: "demonstrated" }],
    resume_match: null,
    resume_guidance: { status: "multiple-matches", label: "Multiple matches", detail: "Two current resumes cover the same verified vault evidence." },
  } });

  await openJob();

  const results = host.querySelectorAll(".job-fit-result");
  expect(results).toHaveLength(2);
  expect(results[0]?.textContent).toContain("Career fitStrong fit");
  expect(results[1]?.textContent).toContain("Resume matchMultiple matches");
  expect(results[1]?.textContent).toContain("same verified vault evidence");
  expect(host.textContent).not.toContain("No matching directional resume was identified");
});

it("queues a slow screen and renders its background result without blocking the job panel", async () => {
  const result = { status: "complete" as const, cached: false, result: {
    job_id: "one", fit: "good_match", fit_label: "Good fit", screening_label: "Quick screen" as const, eligibility: "eligible",
    eligibility_label: "Eligible", recommendation: "pursue", recommendation_label: "Pursue", confidence: "medium" as const,
    strengths: [], gaps: [], unknowns: [], reasoning_summary: "Relevant support experience.",
    evidence_coverage: "good" as const, evidence_strategy: "posting-wide" as const, posting_coverage: "complete" as const, evidence_used: [],
  } };
  vi.useFakeTimers();
  vi.mocked(api.screenJob).mockResolvedValue({ status: "queued", job_id: "one", message: "Analysis queued." });
  vi.mocked(api.getJobScreenStatus)
    .mockResolvedValueOnce({ status: "idle", job_id: "one" })
    .mockResolvedValue(result);

  await openJob();
  await click("Screen job");
  expect(host.textContent).toContain("Analysis queued");
  expect(host.textContent).toContain("keep reviewing");

  await act(async () => { await vi.advanceTimersByTimeAsync(1000); });

  expect(api.getJobScreenStatus).toHaveBeenCalledWith("one");
  expect(host.textContent).toContain("Good fit");
  expect(host.textContent).toContain("Relevant support experience.");
});

it("shows persisted screening and recommendation metadata without waiting for detail calls", async () => {
  const screenedJob: Job = {
    ...job,
    quick_screen: { status: "complete", label: "Good fit", resume_name: "Support Engineer", generated_at: "2026-09-08T12:00:00Z" },
    personalization: { hot: true, hot_reasons: ["career_fit"], hot_score: 0.9, hot_label: "Hot job", interest_label: "High", company_label: "Positive" },
  };
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [screenedJob], count: 1, reviewable_count: 1 });
  vi.mocked(api.getJobScreenStatus).mockImplementation(() => new Promise(() => {}));
  vi.mocked(api.getJobFeedback).mockImplementation(() => new Promise(() => {}));
  vi.mocked(api.getResumeRecommendation).mockImplementation(() => new Promise(() => {}));

  await openJob();

  expect(host.textContent).toContain("Quick screen complete");
  expect(host.textContent).toContain("Hot recommendation");
  expect(host.textContent).not.toContain("Checking screen status");
  expect(host.textContent).not.toContain("Loading recommendation details");
});

it("shows saved job feedback without waiting for the resume recommendation", async () => {
  vi.mocked(api.getResumeRecommendation).mockImplementation(() => new Promise(() => {}));
  vi.mocked(api.getJobFeedback).mockResolvedValue({
    job_id: "one",
    latest: { action: "interested", reasons: [], created_at: "2026-09-09T12:00:00Z" },
    personalization: {
      hot_label: "Recommended", fit_score: 0.7, interest_score: 0.85,
      company_score: 0.5, fit_label: "Strong", interest_label: "High",
      company_label: "Neutral", confidence: "medium", reasons: [], hot: true,
      hot_reasons: ["interest"],
    },
  });

  await openJob();

  expect(host.textContent).toContain("Interested ✓");
});

it("restores an in-progress screen when the job is reopened before other details finish loading", async () => {
  vi.useFakeTimers();
  vi.mocked(api.screenJob).mockResolvedValue({ status: "queued", job_id: "one", message: "Analysis queued." });
  vi.mocked(api.getJobScreenStatus)
    .mockResolvedValueOnce({ status: "idle", job_id: "one" })
    .mockResolvedValue({ status: "running", job_id: "one", message: "Analyzing in the background." });

  await openJob();
  await click("Screen job");
  await act(async () => (host.querySelector('[aria-label="Close job details"]') as HTMLButtonElement).click());
  vi.mocked(api.getResumeRecommendation).mockImplementationOnce(() => new Promise(() => {}));
  await act(async () => (host.querySelector(".job-row") as HTMLButtonElement).click());

  expect(host.textContent).toContain("Analyzing in background");
  expect([...host.querySelectorAll("button")].some((button) => button.textContent === "Screen job")).toBe(false);
  expect(api.screenJob).toHaveBeenCalledTimes(1);
});

it("keeps a long-running screen visibly active past the old polling cutoff", async () => {
  vi.useFakeTimers();
  let statusChecks = 0;
  vi.mocked(api.screenJob).mockResolvedValue({ status: "queued", job_id: "one", message: "Analysis queued." });
  vi.mocked(api.getJobScreenStatus).mockImplementation(async () => {
    statusChecks += 1;
    return statusChecks === 1
      ? { status: "idle", job_id: "one" }
      : { status: "running", job_id: "one", message: "Analyzing in the background." };
  });

  await openJob();
  await click("Screen job");
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });

  expect(host.textContent).toContain("Analyzing in background");
  expect(host.textContent).not.toContain("You can try again");
  expect([...host.querySelectorAll("button")].some((button) => button.textContent === "Screen job")).toBe(false);
  expect(api.screenJob).toHaveBeenCalledTimes(1);
});

it("notices a scheduled recommendation refresh after starting idle", async () => {
  vi.useFakeTimers();
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [], count: 0, reviewable_count: 1 });
  const base: Omit<api.ScrapeSchedule, "current_stage"> = {
    configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York",
    next_run: null, last_run: null, service_status: "online", screening_enabled: true,
    screening_max_jobs: 15, screening_available: true,
  };
  vi.mocked(api.getScrapeSchedule)
    .mockResolvedValueOnce({ ...base, current_stage: "idle", recommendation_revision: "0" })
    .mockResolvedValueOnce({ ...base, current_stage: "searching", recommendation_revision: "0" })
    .mockResolvedValue({ ...base, current_stage: "screening", recommendation_revision: "1" });

  await act(async () => root.render(<JobsPage />));
  await act(async () => { await vi.advanceTimersByTimeAsync(30_000); });
  expect(host.textContent).toContain("Finding new jobs");
  await act(async () => { await vi.advanceTimersByTimeAsync(3_000); });

  expect(api.getJobs).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("Screening recommendations");
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
      reasoning_summary: `${fitLabel} evidence.`,
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
  expect(host.textContent).toContain("Analysis queued");

  await act(async () => (host.querySelectorAll(".job-row")[1] as HTMLButtonElement).click());
  expect(host.textContent).toContain("Screen job");
  expect(host.textContent).not.toContain("Analysis queued");

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
