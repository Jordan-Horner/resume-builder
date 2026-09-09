import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getJobs,
  hideJobPosting,
  getJobScreenStatus,
  estimateJobSalary,
  getSavedJobSalary,
  getOnboardingStatus,
  getSystemStatus,
  getScrapeSchedule,
  getScreeningBackfill,
  markJobApplied,
  markApplicationReapplied,
  markJobNotInterested,
  saveJobFeedback,
  screenJob,
  startScreeningBackfill,
  skipOnboarding,
  uploadResume,
} from "./api";

afterEach(() => {
  vi.restoreAllMocks();
  vi.useRealTimers();
});

describe("dashboard API client", () => {
  it("starts a screening backfill without starting job discovery", async () => {
    const payload = { status: "running", message: "Screening…" };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockImplementation(async () =>
      new Response(JSON.stringify(payload), {
        status: 202,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await startScreeningBackfill();
    await getScreeningBackfill();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/jobs/screening-backfill", expect.objectContaining({ method: "POST", signal: expect.any(AbortSignal) }));
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/jobs/screening-backfill", expect.objectContaining({ signal: expect.any(AbortSignal) }));
    expect(fetchMock).not.toHaveBeenCalledWith("/api/job-sources/scan", expect.anything());
  });

  it("sends search and normalized work-mode filters", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ jobs: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await getJobs({
      search: "platform engineer",
      workMode: "hybrid",
      dateDays: 7,
      employmentType: "fulltime",
    });

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs?search=platform+engineer&work_mode=hybrid&date_days=7&employment_type=fulltime",
      undefined,
    );
  });

  it.each([
    ["not interested", markJobNotInterested, "/api/jobs/job-1/not-interested"],
    ["applied", markJobApplied, "/api/jobs/job-1/applied"],
    ["estimate salary", estimateJobSalary, "/api/jobs/job-1/estimate-salary"],
  ])("posts an explicit %s disposition", async (_label, action, endpoint) => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await action("job-1");

    expect(fetchMock).toHaveBeenCalledWith(endpoint, expect.objectContaining({ method: "POST" }));
  });

  it("records the resume used with an application", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await markJobApplied("job-1", "resumes/baselines/platform.md");

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/job-1/applied",
      expect.objectContaining({
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ resume_id: "resumes/baselines/platform.md" }),
      }),
    );
  });

  it("records an explicit reapplication", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({}), {
        status: 201,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await markApplicationReapplied("APP-1");

    expect(fetchMock).toHaveBeenCalledWith("/api/applications/APP-1/reapplied", { method: "POST" });
  });

  it("sends a posting-hide reason separately from preference feedback", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ job_id: "job-1", reason: "closed", personalization_updated: false }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await hideJobPosting("job-1", "closed");

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/job-1/hide", expect.objectContaining({
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ reason: "closed" }),
      signal: expect.any(AbortSignal),
    }));
  });

  it("stops waiting when saving job feedback takes too long", async () => {
    vi.useFakeTimers();
    vi.spyOn(globalThis, "fetch").mockImplementation((_url, init) =>
      new Promise((_resolve, reject) => {
        init?.signal?.addEventListener("abort", () => {
          reject(new DOMException("Aborted", "AbortError"));
        });
      }),
    );

    const expectation = expect(
      saveJobFeedback("job-1", "interested", []),
    ).rejects.toThrow("Saving took too long. Please try again.");
    await vi.advanceTimersByTimeAsync(10_000);

    await expectation;
  });

  it("loads a saved salary estimate without requesting a new one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    expect(await getSavedJobSalary("job-1")).toBeNull();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/jobs/job-1/salary-estimate",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
  });

  it("loads the authoritative screening status separately from an explicit screen", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "queued", job_id: "job-1" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "complete" }), {
        status: 202, headers: { "Content-Type": "application/json" },
      }));

    await getJobScreenStatus("job-1");
    await screenJob("job-1");

    expect(fetchMock).toHaveBeenNthCalledWith(
      1,
      "/api/jobs/job-1/screen-status",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );
    expect(fetchMock).toHaveBeenNthCalledWith(
      2,
      "/api/jobs/job-1/screen",
      expect.objectContaining({ method: "POST", signal: expect.any(AbortSignal) }),
    );
  });

  it("loads and defers onboarding through explicit endpoints", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(
        new Response(JSON.stringify({ needs_onboarding: true, step: "resume" }), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      )
      .mockResolvedValueOnce(new Response(null, { status: 204 }));

    await getOnboardingStatus();
    await skipOnboarding();

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/onboarding", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/onboarding/skip", { method: "POST" });
  });

  it("uploads a resume as multipart form data", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ filename: "resume.md", registered_sources: 1 }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    const file = new File(["# Experience"], "resume.md", { type: "text/markdown" });

    await uploadResume(file);

    const [, options] = fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe("/api/career-material/resumes");
    expect(options?.method).toBe("POST");
    expect(options?.body).toBeInstanceOf(FormData);
    expect((options?.body as FormData).get("file")).toBe(file);
  });

  it("explains when an older server returns the app shell for a new API route", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response("<!doctype html><html></html>", {
        status: 200,
        headers: { "Content-Type": "text/html" },
      }),
    );

    await expect(getScrapeSchedule()).rejects.toThrow("portal and server are out of sync");
  });

  it("loads component health from the portal", async () => {
    const payload = { status: "healthy", components: [] };
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify(payload), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );

    await expect(getSystemStatus()).resolves.toEqual(payload);
    expect(fetchMock).toHaveBeenCalledWith("/api/system/status", undefined);
  });
});
