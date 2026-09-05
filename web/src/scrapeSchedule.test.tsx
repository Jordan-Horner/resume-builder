// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getJobSources, getScrapeSchedule, saveScrapeSchedule } from "./api";
import { JobSources } from "./pages/JobSources";

vi.mock("./api", () => ({
  getJobSources: vi.fn(), setJobSource: vi.fn(), startJobScan: vi.fn(),
  getScrapeSchedule: vi.fn(), saveScrapeSchedule: vi.fn(),
}));

const schedule = { configured: true, enabled: true, times: ["08:00"], timezone: "America/New_York", next_run: "2026-09-06T08:00:00-04:00", last_run: null, service_status: "online" as const };
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getJobSources).mockResolvedValue({ providers: [], scan: { status: "idle" } });
  vi.mocked(getScrapeSchedule).mockResolvedValue(schedule);
  vi.mocked(saveScrapeSchedule).mockResolvedValue(schedule);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.restoreAllMocks(); });

it("presents simple frequency presets backed by exact run times", async () => {
  await act(async () => root.render(<JobSources />));
  expect(host.textContent).toContain("Automatic scraping");
  expect(host.textContent).toContain("Once daily");
  expect(host.textContent).toContain("Twice daily");
  expect(host.textContent).toContain("Custom");
  expect(host.textContent).toContain("8:00 AM");
  expect(host.textContent).toContain("America/New_York");
  expect(host.textContent).toContain("Scheduler online");
});

it("saves the twice-daily preset as two canonical times", async () => {
  await act(async () => root.render(<JobSources />));
  const twice = [...host.querySelectorAll("button")].find((item) => item.textContent === "Twice daily") as HTMLButtonElement;
  await act(async () => twice.click());
  const save = [...host.querySelectorAll("button")].find((item) => item.textContent === "Save schedule") as HTMLButtonElement;
  await act(async () => save.click());
  expect(saveScrapeSchedule).toHaveBeenCalledWith(true, ["08:00", "17:00"]);
});

it("uses the toggle immediately while leaving manual searches available", async () => {
  vi.mocked(getJobSources).mockResolvedValue({ providers: [{ id: "indeed", name: "Indeed", enabled: true, detail: "Ready" }], scan: { status: "idle" } });
  vi.mocked(saveScrapeSchedule).mockResolvedValue({ ...schedule, enabled: false, next_run: null, service_status: "offline" });
  await act(async () => root.render(<JobSources />));

  const toggle = host.querySelector('input[aria-label="Automatic scraping"]') as HTMLInputElement;
  await act(async () => toggle.click());

  expect(saveScrapeSchedule).toHaveBeenCalledWith(false, ["08:00"]);
  const manual = [...host.querySelectorAll("button")].find((item) => item.textContent === "Find jobs now") as HTMLButtonElement;
  expect(manual.disabled).toBe(false);
});
