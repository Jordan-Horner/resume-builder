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
  getJobSources: vi.fn(), startJobScan: vi.fn(),
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
  vi.mocked(api.getSearchPreferences).mockResolvedValue({ status: "active", revision: "one", titles: [], skill_terms: [], country: "US", work_modes: ["remote"], onsite_locations: [], remote_location_terms: [], compensation: { skipped: true, minimum: null, target: null, currency: null, period: null } });
  vi.mocked(api.getBlockedCompanies).mockResolvedValue({ companies: [] });
  vi.mocked(api.getResumeRecommendation).mockResolvedValue({ status: "unavailable", recommended_resume: null, match: null, target: null, message: "None" });
  vi.mocked(api.getJobs).mockResolvedValue({ jobs: [job], count: 1, reviewable_count: 1 });
  vi.mocked(api.markJobApplied).mockResolvedValue({});
  vi.mocked(api.markJobNotInterested).mockResolvedValue(undefined);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });
async function click(text: string) {
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === text)?.click());
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
