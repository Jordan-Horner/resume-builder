// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getApplications, markApplicationReapplied } from "./api";
import { ApplicationsPage } from "./pages/ApplicationsPage";

vi.mock("./api", () => ({
  getApplications: vi.fn(),
  markApplicationReapplied: vi.fn(),
}));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("surfaces a reopened application and records a deliberate second attempt", async () => {
  vi.mocked(getApplications)
    .mockResolvedValueOnce([
      {
        id: "APP-1",
        company: "Example",
        role: "Support Engineer",
        job_id: "job-1",
        application_url: "https://example.invalid/jobs/1",
        applied_on: "2026-08-01",
        current_status: "no_response",
        events: [],
        resume: null,
        resume_attribution: "not_recorded",
        reapplication: {
          application_id: "APP-1",
          prior_job_id: "job-1",
          job_id: "job-1",
          kind: "reopened",
          company: "Example",
          role: "Support Engineer",
          url: "https://example.invalid/jobs/1",
          detected_at: "2026-09-08T12:00:00Z",
          reason: "The previously applied posting reopened.",
        },
      },
    ])
    .mockResolvedValueOnce([]);
  vi.mocked(markApplicationReapplied).mockResolvedValue({});

  await act(async () => root.render(<ApplicationsPage />));

  expect(host.textContent).toContain("Reopened");
  await act(async () => host.querySelector<HTMLButtonElement>(".application-summary")?.click());
  expect(host.textContent).toContain("This posting reopened.");
  expect(host.textContent).toContain("I applied again");

  await act(async () => {
    Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "I applied again")?.click();
  });

  expect(markApplicationReapplied).toHaveBeenCalledWith("APP-1");
  expect(host.textContent).toContain("Support Engineer was recorded as a new application.");
});
