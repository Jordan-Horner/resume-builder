// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getOnboardingStatus, uploadResume, backOnboarding, startOnboarding, previewRoleTitles, answerOnboarding } from "./api";
import { OnboardingPage } from "./pages/OnboardingPage";
import type { OnboardingStatus } from "./types";

vi.mock("./api", () => ({
  activateJobSearch: vi.fn(),
  answerOnboarding: vi.fn(),
  backOnboarding: vi.fn(),
  getOnboardingStatus: vi.fn(),
  skipOnboarding: vi.fn(),
  startOnboarding: vi.fn(),
  uploadResume: vi.fn(),
  previewRoleTitles: vi.fn(),
}));

const initial: OnboardingStatus = {
  needs_onboarding: true,
  step: "resume",
  progress: 1,
  resume_count: 0,
  resume_names: [],
  openrouter_configured: false,
  setup: null,
};

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

it("lets users import several career documents before continuing", async () => {
  vi.mocked(uploadResume)
    .mockResolvedValueOnce({ filename: "current-resume.pdf", registered_sources: 1 })
    .mockResolvedValueOnce({ filename: "linkedin-profile.pdf", registered_sources: 2 });
  vi.mocked(getOnboardingStatus).mockResolvedValue({
    ...initial,
    step: "ai_choice",
    resume_count: 2,
    resume_names: ["current-resume.pdf", "linkedin-profile.pdf"],
  });
  await act(async () => root.render(<OnboardingPage initial={initial} onComplete={vi.fn()} />));

  const input = host.querySelector('input[type="file"]') as HTMLInputElement;
  const files = [
    new File(["resume"], "current-resume.pdf", { type: "application/pdf" }),
    new File(["profile"], "linkedin-profile.pdf", { type: "application/pdf" }),
  ];
  Object.defineProperty(input, "files", { configurable: true, value: files });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  const add = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Add 2 sources");
  await act(async () => add?.click());

  expect(uploadResume).toHaveBeenCalledTimes(2);
  expect(host.textContent).toContain("current-resume.pdf");
  expect(host.textContent).toContain("linkedin-profile.pdf");
  expect(host.textContent).toContain("Add more");
  expect(host.textContent).toContain("Continue");
  expect(getOnboardingStatus).not.toHaveBeenCalled();

  const continueButton = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Continue");
  await act(async () => continueButton?.click());
  expect(getOnboardingStatus).toHaveBeenCalledTimes(1);
});

it("retries only the unfinished files after a partial import", async () => {
  vi.mocked(uploadResume)
    .mockResolvedValueOnce({ filename: "current-resume.pdf", registered_sources: 1 })
    .mockRejectedValueOnce(new Error("Could not read LinkedIn profile"))
    .mockResolvedValueOnce({ filename: "linkedin-profile.pdf", registered_sources: 2 });
  await act(async () => root.render(<OnboardingPage initial={initial} onComplete={vi.fn()} />));

  const input = host.querySelector('input[type="file"]') as HTMLInputElement;
  const files = [
    new File(["resume"], "current-resume.pdf", { type: "application/pdf" }),
    new File(["profile"], "linkedin-profile.pdf", { type: "application/pdf" }),
  ];
  Object.defineProperty(input, "files", { configurable: true, value: files });
  await act(async () => input.dispatchEvent(new Event("change", { bubbles: true })));
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Add 2 sources")?.click());

  expect(host.textContent).toContain("current-resume.pdf");
  expect(host.textContent).toContain("Could not read LinkedIn profile");
  expect(host.textContent).toContain("1 file selected");
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Add 1 source")?.click());

  expect(uploadResume).toHaveBeenCalledTimes(3);
  expect(vi.mocked(uploadResume).mock.calls.map(([file]) => file.name)).toEqual([
    "current-resume.pdf",
    "linkedin-profile.pdf",
    "linkedin-profile.pdf",
  ]);
});

const rolesStatus: OnboardingStatus = {
  ...initial, step: "roles", progress: 2, resume_count: 1,
  setup: { session_id: "session-one", status: "in_progress", step: "roles", roles: [{ role_id: "support", title: "Support Engineer", group: "related", intent: "search", reason: "Experience" }], eligibility: null, location: null, compensation: null },
};

it("uses the backend transition when returning to the suggestion method", async () => {
  localStorage.clear();
  vi.mocked(startOnboarding).mockClear();
  vi.mocked(backOnboarding).mockResolvedValue({ ...rolesStatus, step: "ai_choice", progress: 1 });
  await act(async () => root.render(<OnboardingPage initial={rolesStatus} onComplete={vi.fn()} />));
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Back")?.click());
  expect(backOnboarding).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("How should we suggest roles?");
  expect(startOnboarding).not.toHaveBeenCalled();
});

it("submits backend-normalized roles instead of calculating role decisions", async () => {
  localStorage.clear();
  vi.mocked(previewRoleTitles).mockResolvedValue({ titles: ["Support Engineer"], remaining: 21, minimum_length: 2, maximum_length: 150 });
  vi.mocked(answerOnboarding).mockResolvedValue({ ...rolesStatus, step: "location", progress: 3 });
  await act(async () => root.render(<OnboardingPage initial={rolesStatus} onComplete={vi.fn()} />));
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Continue")?.click());
  expect(previewRoleTitles).toHaveBeenCalledWith("onboarding", ["Support Engineer"]);
  expect(answerOnboarding).toHaveBeenCalledWith("roles", { titles: ["Support Engineer"] });
});

it("preserves browser edits while including newly returned suggestions", async () => {
  localStorage.setItem("onboarding-roles-v1:session-one", JSON.stringify({ titles: ["Customer Engineer"], input: "Technical", sourceTitles: ["Support Engineer"] }));
  const status: OnboardingStatus = { ...rolesStatus, setup: { ...rolesStatus.setup!, roles: [...rolesStatus.setup!.roles, { role_id: "platform", title: "Platform Engineer", group: "related", intent: "search", reason: "New suggestion" }] } };
  await act(async () => root.render(<OnboardingPage initial={status} onComplete={vi.fn()} />));
  const titles = [...host.querySelectorAll(".role-bubble > span")].map((item) => item.textContent);
  expect(titles).toEqual(["Customer Engineer", "Platform Engineer"]);
  expect((host.querySelector("#new-role") as HTMLInputElement).value).toBe("Technical");
});
