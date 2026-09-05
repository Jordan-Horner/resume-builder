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

it("cannot mutate a schedule while its saved state is pending or unavailable", async () => {
  vi.mocked(saveScrapeSchedule).mockClear();
  let reject!: (error: Error) => void;
  vi.mocked(getScrapeSchedule).mockReturnValueOnce(new Promise((_resolve, fail) => { reject = fail; }));
  await act(async () => root.render(<JobSources />));
  expect(host.textContent).toContain("Loading schedule");
  expect(host.querySelector('input[aria-label="Automatic scraping"]')).toBeNull();
  expect([...host.querySelectorAll("button")].some((button) => button.textContent === "Save schedule")).toBe(false);
  await act(async () => reject(new Error("Schedule unavailable")));
  expect(host.textContent).toContain("Schedule unavailable");
  vi.mocked(getScrapeSchedule).mockResolvedValueOnce({ ...schedule, enabled: false, times: ["19:30"] });
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Retry schedule")?.click());
  expect((host.querySelector('input[aria-label="Automatic scraping"]') as HTMLInputElement).checked).toBe(false);
  expect(host.textContent).toContain("7:30 PM");
  expect(saveScrapeSchedule).not.toHaveBeenCalled();
});

it("locks schedule inputs until a save completes", async () => {
  let resolve!: (value: typeof schedule) => void;
  vi.mocked(saveScrapeSchedule).mockReturnValueOnce(new Promise((done) => { resolve = done; }));
  await act(async () => root.render(<JobSources />));
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Twice daily")?.click());
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Save schedule")?.click());
  const controls = host.querySelectorAll('.scrape-schedule button, .scrape-schedule input');
  expect([...controls].every((control) => (control as HTMLButtonElement).disabled)).toBe(true);
  await act(async () => resolve({ ...schedule, times: ["08:00", "17:00"] }));
  expect(host.textContent).toContain("5:00 PM");
});
