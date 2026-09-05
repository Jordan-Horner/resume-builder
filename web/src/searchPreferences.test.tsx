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
  skill_terms: [],
  country: "United States",
  work_modes: ["remote"],
  onsite_locations: [],
  remote_location_terms: ["USA"],
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

it("keeps the current titles when the backend reports exhausted skill capacity", async () => {
  vi.mocked(previewRoleTitles).mockRejectedValueOnce(new Error("Remove a role or skill before adding another."));
  await act(async () => root.render(<SearchPreferencesSection />));
  const input = host.querySelector('input[placeholder="e.g. Site Reliability Engineer"]') as HTMLInputElement;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")?.set?.call(input, "Platform Engineer");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Add")?.click());
  expect(host.textContent).toContain("Remove a role or skill");
  expect([...host.querySelectorAll(".role-bubble > span")].map((item) => item.textContent)).toEqual(["Support Engineer"]);
  expect(input.value).toBe("Platform Engineer");
});
