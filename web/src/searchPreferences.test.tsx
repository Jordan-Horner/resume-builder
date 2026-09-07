// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getSearchPreferences, saveSearchPreferences, previewRoleTitles } from "./api";
import { SearchPreferencesSection } from "./pages/SearchPreferencesSection";
import type { SearchPreferences } from "./types";

vi.mock("./api", () => ({ getSearchPreferences: vi.fn(), saveSearchPreferences: vi.fn(), previewRoleTitles: vi.fn() }));

const preferences: SearchPreferences = {
  status: "active",
  revision: "rev-1",
  titles: ["Support Engineer"],
  country: "United States",
  work_modes: ["remote"],
  onsite_locations: [],
  remote_location_terms: ["USA"],
  clearance_preference: "neutral",
  preferred_job_attributes: ["Production ownership"],
  avoided_job_attributes: ["Phone-first support"],
  compensation: { skipped: false, minimum: 80000, target: 125000, currency: "USD", period: "year" },
};
let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.mocked(previewRoleTitles).mockImplementation(async (_scope, titles) => ({ titles, remaining: 20, minimum_length: 2, maximum_length: 150 }));
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getSearchPreferences).mockResolvedValue(preferences);
  vi.mocked(saveSearchPreferences).mockImplementation(async (value) => ({ ...value, revision: "rev-2" }));
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });

it("adds multiple searchable title bubbles and saves them as active preferences", async () => {
  await act(async () => root.render(<SearchPreferencesSection />));
  const input = host.querySelector('input[placeholder="e.g. Site Reliability Engineer"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Platform Engineer");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  const add = [...host.querySelectorAll("button")].find((item) => item.textContent === "Add") as HTMLButtonElement;
  await act(async () => add.click());
  expect(host.textContent).toContain("Support Engineer");
  expect(host.textContent).toContain("Platform Engineer");

  const save = [...host.querySelectorAll("button")].find((item) => item.textContent === "Save changes") as HTMLButtonElement;
  await act(async () => save.click());
  expect(saveSearchPreferences).toHaveBeenCalledWith(expect.objectContaining({
    titles: ["Support Engineer", "Platform Engineer"],
    revision: "rev-1",
  }));
});

it("adds and removes plain-language job preferences", async () => {
  await act(async () => root.render(<SearchPreferencesSection />));
  const disclosure = host.querySelector(".settings-disclosure") as HTMLDetailsElement;
  expect(disclosure.open).toBe(false);
  expect(disclosure.textContent).toContain("2 saved");
  const input = host.querySelector('input[placeholder="e.g. Complex troubleshooting"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Engineering ownership");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => (input.closest("form")?.querySelector("button") as HTMLButtonElement).click());
  expect(host.textContent).toContain("Engineering ownership");
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.getAttribute("aria-label") === "Remove Phone-first support")?.click());
  const save = Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Save changes") as HTMLButtonElement;
  await act(async () => save.click());
  expect(saveSearchPreferences).toHaveBeenCalledWith(expect.objectContaining({
    preferred_job_attributes: ["Production ownership", "Engineering ownership"],
    avoided_job_attributes: [],
  }));
});

it("keeps the current titles when the backend reports exhausted title capacity", async () => {
  vi.mocked(previewRoleTitles).mockRejectedValueOnce(new Error("Remove a job title before adding another."));
  await act(async () => root.render(<SearchPreferencesSection />));
  const input = host.querySelector('input[placeholder="e.g. Site Reliability Engineer"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Platform Engineer");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Add")?.click());
  expect(host.textContent).toContain("Remove a job title");
  expect([...host.querySelectorAll(".role-bubble > span")].map((item) => item.textContent)).toEqual(["Support Engineer"]);
  expect(input.value).toBe("Platform Engineer");
});

it("saves clearance preference independently from the job-list filter", async () => {
  await act(async () => root.render(<SearchPreferencesSection />));
  const select = host.querySelector('option[value="neutral"]')?.parentElement as HTMLSelectElement;
  await act(async () => {
    select.value = "prefer";
    select.dispatchEvent(new Event("change", { bubbles: true }));
  });
  const save = [...host.querySelectorAll("button")].find((item) => item.textContent === "Save changes") as HTMLButtonElement;
  await act(async () => save.click());
  expect(saveSearchPreferences).toHaveBeenCalledWith(expect.objectContaining({ clearance_preference: "prefer" }));
});
