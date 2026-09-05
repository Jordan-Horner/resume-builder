// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { backOnboarding, startOnboarding, previewRoleTitles, answerOnboarding } from "./api";
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
