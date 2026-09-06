import { afterEach, describe, expect, it, vi } from "vitest";
import {
  getJobs,
  estimateJobSalary,
  getSavedJobSalary,
  getSavedJobScreen,
  getOnboardingStatus,
  getSystemStatus,
  getScrapeSchedule,
  markJobApplied,
  markJobNotInterested,
  screenJob,
  skipOnboarding,
  uploadResume,
} from "./api";

afterEach(() => vi.restoreAllMocks());

describe("dashboard API client", () => {
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

    expect(fetchMock).toHaveBeenCalledWith(endpoint, { method: "POST" });
  });

  it("loads a saved salary estimate without requesting a new one", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(null, { status: 204 }),
    );

    expect(await getSavedJobSalary("job-1")).toBeNull();

    expect(fetchMock).toHaveBeenCalledWith("/api/jobs/job-1/salary-estimate", undefined);
  });

  it("loads cached screening separately from an explicit screen", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch")
      .mockResolvedValueOnce(new Response(null, { status: 204 }))
      .mockResolvedValueOnce(new Response(JSON.stringify({ status: "complete" }), {
        status: 200, headers: { "Content-Type": "application/json" },
      }));

    expect(await getSavedJobScreen("job-1")).toBeNull();
    await screenJob("job-1");

    expect(fetchMock).toHaveBeenNthCalledWith(1, "/api/jobs/job-1/screen", undefined);
    expect(fetchMock).toHaveBeenNthCalledWith(2, "/api/jobs/job-1/screen", { method: "POST" });
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
