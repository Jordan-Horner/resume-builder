// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { configureOpenRouter, getIntegrations } from "./api";
import { IntegrationsSection } from "./pages/IntegrationsPage";

vi.mock("./api", () => ({ configureOpenRouter: vi.fn(), getIntegrations: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(getIntegrations).mockResolvedValue([{ id: "openrouter", name: "OpenRouter", description: "AI provider", status: "not_connected", detail: "API key not available" }]);
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.resetAllMocks(); });

async function openAndSave() {
  await act(async () => root.render(<IntegrationsSection />));
  await act(async () => host.querySelector<HTMLButtonElement>(".integration-summary")!.click());
  const input = host.querySelector<HTMLInputElement>("#openrouter-key")!;
  expect(input.type).toBe("password");
  expect(host.textContent).not.toContain("Copy setup command");
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "fixture-key");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector<HTMLButtonElement>(".openrouter-setup button")!.click());
}

it("connects OpenRouter from Settings and clears the key after saving", async () => {
  vi.mocked(configureOpenRouter).mockResolvedValue({ connected: true, message: "OpenRouter connected." });
  await openAndSave();
  expect(configureOpenRouter).toHaveBeenCalledWith("fixture-key");
  expect(host.querySelector<HTMLInputElement>("#openrouter-key")!.value).toBe("");
  expect(host.textContent).toContain("OpenRouter connected.");
});

it("shows verification errors without losing the entered key", async () => {
  vi.mocked(configureOpenRouter).mockRejectedValue(new Error("OpenRouter rejected this key."));
  await openAndSave();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("rejected");
  expect(host.querySelector<HTMLInputElement>("#openrouter-key")!.value).toBe("fixture-key");
});
