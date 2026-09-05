// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getResumes, getSkills, setSkillSearch } from "./api";
import { ResumesPage } from "./pages/ResumesPage";
import { SkillsPage } from "./pages/SkillsPage";
import type { CareerSkill } from "./types";

vi.mock("./api", () => ({
  getResumes: vi.fn(),
  getSkills: vi.fn(),
  setSkillSearch: vi.fn(),
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

it("renders the server-organized resume library without classifying resumes", async () => {
  vi.mocked(getResumes).mockResolvedValue({ sections: [
    { id: "originals", title: "Original resumes", description: "Imported evidence.", items: [
      { id: "SRC-001", name: "resume.pdf", kind: "original", status_label: "Imported", status_tone: "neutral", updated_at: "2026-09-03T12:00:00Z", detail: "PDF · Career evidence", error: null, preview_url: null, preview_message: "Build a directional resume to create an HTML preview." },
    ] },
    { id: "directional", title: "Directional resumes", description: "Reusable role directions.", items: [
      { id: "resumes/baselines/support.md", name: "Support Operations", kind: "directional", status_label: "In review", status_tone: "attention", updated_at: "2026-09-05T12:00:00Z", detail: "Reusable direction", error: null, preview_url: "/api/resume-preview?resume_id=resumes%2Fbaselines%2Fsupport.md", preview_message: null },
    ] },
  ] });

  await act(async () => root.render(<ResumesPage />));

  expect(host.textContent).toContain("Original resumes");
  expect(host.textContent).toContain("resume.pdf");
  expect(host.textContent).toContain("Directional resumes");
  expect(host.textContent).toContain("Support Operations");

  const directional = Array.from(host.querySelectorAll("button")).find((button) => button.textContent?.includes("Support Operations"));
  await act(async () => directional?.click());

  expect(host.querySelector("iframe")?.getAttribute("src")).toBe("/api/resume-preview?resume_id=resumes%2Fbaselines%2Fsupport.md");
  expect(host.textContent).toContain("Back to resumes");
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
