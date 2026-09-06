// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getResumes, restoreResume, uploadResume } from "./api";
import { ResumesPage } from "./pages/ResumesPage";

vi.mock("./api", () => ({
  getResumes: vi.fn(),
  restoreResume: vi.fn(),
  uploadResume: vi.fn(),
}));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

it("adds more career material after onboarding", async () => {
  vi.mocked(getResumes).mockResolvedValue({ sections: [
    { id: "directional", title: "Directional resumes", description: "Reusable role directions.", items: [] },
    { id: "tailored", title: "Tailored resumes", description: "Job-specific resumes.", items: [] },
    { id: "retired", title: "Retired resumes", description: "Hidden from matching.", items: [] },
  ] });
  vi.mocked(uploadResume).mockResolvedValue({ filename: "older-resume.pdf", registered_sources: 2 });

  await act(async () => root.render(<ResumesPage />));
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Add career material")?.click());
  const input = host.querySelector('input[type="file"]') as HTMLInputElement;
  const file = new File(["resume"], "older-resume.pdf", { type: "application/pdf" });
  Object.defineProperty(input, "files", { configurable: true, value: [file] });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Add 1 source")?.click());

  expect(uploadResume).toHaveBeenCalledWith(file);
  expect(host.textContent).toContain("older-resume.pdf");
  expect(host.textContent).toContain("Added to your career evidence");
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

it("renders the server-organized resume library without classifying resumes", async () => {
  vi.mocked(getResumes).mockResolvedValue({ sections: [
    { id: "directional", title: "Directional resumes", description: "Reusable role directions.", items: [
      { id: "resumes/baselines/support.md", name: "Support Operations", kind: "directional", updated_at: "2026-09-05T12:00:00Z", detail: "Reusable direction", error: null, preview_url: "/api/resume-preview?resume_id=resumes%2Fbaselines%2Fsupport.md&v=123", preview_message: null },
    ] },
    { id: "tailored", title: "Tailored resumes", description: "Job-specific resumes.", items: [] },
    { id: "retired", title: "Retired resumes", description: "Hidden from matching.", items: [] },
  ] });

  await act(async () => root.render(<ResumesPage />));

  expect(host.textContent).not.toContain("Original resumes");
  expect(host.textContent).not.toContain("resume.pdf");
  expect(host.textContent).toContain("Directional resumes");
  expect(host.textContent).toContain("Support Operations");
  expect(host.textContent).not.toContain("Review out of date");
  expect(host.textContent).not.toContain("View preview");

  const directional = Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.includes("Support Operations"));
  await act(async () => directional?.click());

  expect(host.querySelector("iframe")?.getAttribute("src")).toBe("/api/resume-preview?resume_id=resumes%2Fbaselines%2Fsupport.md&v=123");
  expect(host.querySelector("iframe")?.classList.contains("is-dimmed")).toBe(true);
  expect(host.textContent).toContain("Back to resumes");
  expect(host.textContent).not.toContain("Dim paper");
});

it("keeps retired resumes quiet and restores them on request", async () => {
  vi.mocked(getResumes)
    .mockResolvedValueOnce({ sections: [
      { id: "directional", title: "Directional resumes", description: "Reusable role directions.", items: [] },
      { id: "tailored", title: "Tailored resumes", description: "Job-specific resumes.", items: [] },
      { id: "retired", title: "Retired resumes", description: "Hidden from matching.", items: [
        { id: "resumes/archived/support.md", name: "Support Operations", kind: "directional", status: "retired", updated_at: "2026-09-05T12:00:00Z", detail: "Retired direction", error: null, preview_url: "/api/resume-preview?resume_id=retired", preview_message: null },
      ] },
    ] })
    .mockResolvedValueOnce({ sections: [
      { id: "directional", title: "Directional resumes", description: "Reusable role directions.", items: [] },
      { id: "tailored", title: "Tailored resumes", description: "Job-specific resumes.", items: [] },
      { id: "retired", title: "Retired resumes", description: "Hidden from matching.", items: [] },
    ] });
  vi.mocked(restoreResume).mockResolvedValue({ restored: true, message: "Restored" });

  await act(async () => root.render(<ResumesPage />));
  const summary = host.querySelector("summary") as HTMLElement;
  expect(summary.textContent).toContain("Retired resumes");
  await act(async () => summary.click());
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Restore")?.click());

  expect(restoreResume).toHaveBeenCalledWith("resumes/archived/support.md");
});
