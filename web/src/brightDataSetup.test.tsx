// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { configureBrightData, enrichBrightData, getIntegrations } from "./api";
import { IntegrationsSection } from "./pages/IntegrationsPage";

vi.mock("./api", () => ({ configureBrightData: vi.fn(), enrichBrightData: vi.fn(), getIntegrations: vi.fn() }));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getIntegrations).mockResolvedValue([{
    id: "bright-data",
    name: "Bright Data",
    description: "LinkedIn enrichment",
    status: "not_connected",
    detail: "Not connected",
    settings: { enabled: false, max_records_per_refresh: 100 },
  }]);
});

afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.resetAllMocks(); });

it("saves Bright Data in Integrations with an explicit cap", async () => {
  vi.mocked(configureBrightData).mockResolvedValue({ connected: true, enabled: true, max_records_per_refresh: 75, message: "Bright Data integration saved." });
  await act(async () => root.render(<IntegrationsSection />));
  await act(async () => host.querySelector<HTMLButtonElement>(".integration-summary")!.click());
  const token = host.querySelector<HTMLInputElement>("#bright-data-token")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(token, "fixture-token");
    token.dispatchEvent(new Event("input", { bubbles: true }));
    host.querySelector<HTMLInputElement>('[role="switch"]')!.click();
    const limit = host.querySelector<HTMLInputElement>("#bright-data-limit")!;
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(limit, "75");
    limit.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector<HTMLButtonElement>(".bright-data-setup button")!.click());

  expect(configureBrightData).toHaveBeenCalledWith("fixture-token", true, 75);
  expect(token.value).toBe("");
  expect(host.textContent).toContain("Bright Data integration saved.");
});

it("enriches the existing unresolved inventory without starting a source scan", async () => {
  vi.mocked(getIntegrations).mockResolvedValue([{
    id: "bright-data", name: "Bright Data", description: "LinkedIn enrichment",
    status: "connected", detail: "On", settings: { enabled: true, max_records_per_refresh: 5 },
  }]);
  vi.mocked(enrichBrightData).mockResolvedValue({
    requested: 5, improved: 4, no_change: 1, failed: 0, skipped_cached: 3,
    salary_added: 4, location_added: 0, work_mode_added: 1, apply_links_added: 1,
    message: "Bright Data checked 5 job(s): 4 improved.",
  });
  await act(async () => root.render(<IntegrationsSection />));
  await act(async () => host.querySelector<HTMLButtonElement>(".integration-summary")!.click());
  const button = [...host.querySelectorAll("button")].find((item) => item.textContent === "Enrich missing details now")!;
  await act(async () => button.click());

  expect(enrichBrightData).toHaveBeenCalledOnce();
  expect(host.textContent).toContain("Bright Data checked 5 job(s): 4 improved.");
});
