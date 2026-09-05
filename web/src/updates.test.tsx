// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AboutSection, UpdateNotice, UpdateProvider } from "./updates";
import { getUpdateStatus, type UpdateStatus } from "./api";

vi.mock("./api", () => ({ getUpdateStatus: vi.fn() }));
const available: UpdateStatus = { version: "0.12.0", revision: "a".repeat(40), channel: "main", built_at: "", status: "update_available", latest_revision: "b".repeat(40), release_url: "https://github.com/Jordan-Horner/resume-builder/releases/tag/main-build", last_success_at: null, message: "Update available" };
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  localStorage.clear();
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getUpdateStatus).mockResolvedValue(available);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.useRealTimers(); vi.restoreAllMocks(); });
async function render() { await act(async () => root.render(<UpdateProvider><UpdateNotice /><AboutSection /></UpdateProvider>)); }

it("shares one check and provides release links without an installer", async () => {
  vi.mocked(getUpdateStatus).mockClear();
  await render();
  expect(getUpdateStatus).toHaveBeenCalledTimes(1);
  expect(host.textContent).toContain("Update available");
  expect(host.querySelector('.update-indicator')?.getAttribute('href')).toBe('/settings/about');
  expect(host.querySelector('.about-links a')?.getAttribute('href')).toBe(available.release_url);
  expect([...host.querySelectorAll('button')].map(item => item.textContent)).toEqual(["Dismiss this update notice"]);
});

it("dismisses only the announced revision and shows the next one", async () => {
  vi.useFakeTimers();
  await render();
  await act(async () => (host.querySelector('button') as HTMLButtonElement).click());
  expect(host.querySelector('.update-indicator')).toBeNull();
  expect(host.querySelector('.version-status')?.textContent).toBe('Update available');
  expect(localStorage.getItem("resume-builder.dismissed-update.v1")).toBe(available.latest_revision);
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, latest_revision: "c".repeat(40) });
  await act(async () => vi.advanceTimersByTimeAsync(300000));
  expect(host.querySelector('.update-indicator')).not.toBeNull();
});

it.each(["development", "up_to_date", "ahead", "unavailable"] as const)("does not announce %s as an update", async status => {
  vi.mocked(getUpdateStatus).mockResolvedValue({ ...available, status });
  await render();
  expect(host.querySelector('.update-indicator')).toBeNull();
});

it("shows failure rather than an up-to-date assertion", async () => {
  vi.mocked(getUpdateStatus).mockRejectedValue(new Error("offline"));
  await render();
  expect(host.textContent).toContain("Unable to check");
  expect(host.textContent).not.toContain("Up to date");
});
