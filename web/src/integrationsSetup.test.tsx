// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { getGmailSetup, getIntegrations, startTelegramPairing } from "./api";
import { IntegrationsSection } from "./pages/IntegrationsPage";
import { __resetCachedResources } from "./useCachedResource";

vi.mock("./api", () => ({
  beginGmailAuthorization: vi.fn(),
  configureBrightData: vi.fn(),
  configureOpenRouter: vi.fn(),
  getGmailSetup: vi.fn(),
  getIntegrations: vi.fn(),
  getTelegramPairing: vi.fn(),
  startTelegramPairing: vi.fn(),
}));

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  __resetCachedResources();
  window.localStorage.clear();
  window.history.replaceState({}, "", "/settings/integrations");
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.mocked(getIntegrations).mockResolvedValue([
    { id: "gmail", name: "Gmail", description: "Email updates", status: "not_connected", detail: "Not connected" },
    { id: "telegram", name: "Telegram", description: "Private assistant", status: "not_connected", detail: "Not connected" },
  ]);
  vi.mocked(getGmailSetup).mockResolvedValue({
    connected: false,
    privacy: "Read-only access. Email content is not saved.",
    steps: Array.from({ length: 6 }, (_, index) => ({
      number: index + 1,
      total: 6,
      title: `Google step ${index + 1}`,
      instruction: `Complete Google step ${index + 1}.`,
      link_label: "Open Google",
      link: "https://console.cloud.google.test",
    })),
  });
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.resetAllMocks();
});

async function renderPage() {
  await act(async () => root.render(<IntegrationsSection />));
}

it("guides Gmail setup without exposing a terminal command", async () => {
  await renderPage();
  const gmail = Array.from(host.querySelectorAll<HTMLButtonElement>(".integration-summary")).find((button) => button.textContent?.includes("Gmail"))!;
  await act(async () => gmail.click());

  expect(host.textContent).toContain("Private by design");
  expect(host.textContent).toContain("Step 1 of 6");
  expect(host.textContent).not.toContain("resume-builder");
  expect(host.textContent).not.toContain("setup command");

  for (let index = 0; index < 5; index += 1) {
    await act(async () => host.querySelector<HTMLButtonElement>(".setup-navigation .primary-button")!.click());
  }
  expect(host.textContent).toContain("Google OAuth JSON file");
  expect(window.localStorage.getItem("resume-builder.gmail-step")).toBe("5");
});

it("validates a Telegram bot and presents private pairing actions", async () => {
  vi.mocked(startTelegramPairing).mockResolvedValue({
    session_id: "pairing-session",
    username: "career_helper_bot",
    pairing_url: "https://t.me/career_helper_bot?start=pairing-code",
    qr_url: "/api/integrations/telegram/pairing/pairing-session/qr",
    status: "waiting",
    error: "",
    expires_at: "2026-09-06T12:00:00Z",
  });
  await renderPage();
  const telegram = Array.from(host.querySelectorAll<HTMLButtonElement>(".integration-summary")).find((button) => button.textContent?.includes("Telegram"))!;
  await act(async () => telegram.click());
  const input = host.querySelector<HTMLInputElement>("#telegram-token")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLInputElement.prototype, "value")!.set!.call(input, "private-token");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => host.querySelector<HTMLButtonElement>(".telegram-token-form button")!.click());

  expect(startTelegramPairing).toHaveBeenCalledWith("private-token");
  expect(host.textContent).toContain("Connect @career_helper_bot");
  expect(host.textContent).toContain("Waiting for you to tap Start");
  expect(host.querySelector<HTMLImageElement>(".pairing-stage img")?.src).toContain("/qr");
  expect(host.textContent).not.toContain("private-token");
  expect(host.textContent).not.toContain("resume-builder");
});
