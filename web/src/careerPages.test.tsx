// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getResumes, getSkills, setSkillSearch, uploadResume } from "./api";
import { ResumesPage } from "./pages/ResumesPage";
import { SkillsPage } from "./pages/SkillsPage";
import type { CareerSkill } from "./types";

vi.mock("./api", () => ({
  getResumes: vi.fn(),
  getSkills: vi.fn(),
  setSkillSearch: vi.fn(),
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

it("lets a confirmed vault skill become a search signal", async () => {
  const skill: CareerSkill = { id: "SKILL-001", title: "Incident response", description: "Coordinated production incidents.", status_label: "Confirmed", status_tone: "positive", themes: ["operations"], sources: ["SRC-example"], resumes: ["Support Operations"], search: { enabled: false, can_change: true, disabled_reason: null } };
  vi.mocked(getSkills).mockResolvedValue([skill]);
  vi.mocked(setSkillSearch).mockResolvedValue({ ...skill, search: { ...skill.search, enabled: true } });

  await act(async () => root.render(<SkillsPage />));
  const toggle = host.querySelector('input[type="checkbox"]') as HTMLInputElement;
  await act(async () => toggle.click());

  expect(setSkillSearch).toHaveBeenCalledWith("SKILL-001", true);
  expect(host.textContent).toContain("Used by 1 resume");
  expect(host.textContent).toContain("Search on");
});
