// @vitest-environment jsdom
import { act, type ReactNode } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AssistantPanel from "./AssistantPanel";
import { assistantRequest, type Conversation } from "./api";

const transport = vi.hoisted(() => ({ runAgent: vi.fn() }));

vi.mock("./api", () => ({ assistantRequest: vi.fn() }));
vi.mock("@copilotkit/react-core/v2", () => ({
  CopilotKitProvider: ({ children }: { children: ReactNode }) => children,
  useAgent: () => ({ isReady: true, agent: { setMessages: vi.fn(), addMessage: vi.fn(), abortRun: vi.fn() } }),
  useCopilotKit: () => ({ copilotkit: transport }),
}));
let host: HTMLDivElement;
let root: Root;
const thread: Conversation = {
  id: "saved", resume_id: "resumes/baselines/support.md", title: "Improve summary",
  updated_at: "2026-09-05", runs: [],
  messages: [{ id: "reply", role: "assistant", content: "Saved conversation" }],
  proposals: [{ id: "proposal", status: "pending", message: "", payload: {
    resume_id: "resumes/baselines/support.md", block_id: "summary", before: "Current wording",
    after: "Suggested wording", instruction: "Shorten",
  } }],
};
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  localStorage.setItem("resume-builder.assistant.v1", "saved");
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.mocked(assistantRequest).mockImplementation(async (path) => {
    if (path === "/status") return { configured: true, online: true };
    if (path === "/threads") return { threads: [thread] };
    return thread;
  });
});
afterEach(async () => { await act(async () => root.unmount()); host.remove(); vi.resetAllMocks(); vi.unstubAllGlobals(); });
it("restores server history and routes approval through the backend", async () => {
  await act(async () => root.render(<AssistantPanel open target={null} onClose={() => undefined} />));
  expect(host.textContent).toContain("Saved conversation");
  expect(host.textContent).toContain("Current wording");
  await act(async () => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Use this wording")?.click());
  expect(assistantRequest).toHaveBeenCalledWith("/threads/saved/proposals/proposal/accept", { method: "POST" });
});
it("does not silently switch the attached resume", async () => {
  await act(async () => root.render(<AssistantPanel open target={{ id: "resumes/baselines/cloud.md", name: "Cloud", nonce: 1 }} onClose={() => undefined} />));
  expect(host.textContent).toContain("Discuss this résumé");
  expect(host.textContent).toContain("support");
  expect(assistantRequest).not.toHaveBeenCalledWith("/threads", expect.objectContaining({ method: "POST" }));
});

async function submitMessage() {
  await act(async () => root.render(<AssistantPanel open target={null} onClose={() => undefined} />));
  const input = host.querySelector("textarea")!;
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value")!.set!.call(input, "hi");
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
  await act(async () => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Send")?.click());
}

it("sends on plain HTTP where crypto.randomUUID is unavailable", async () => {
  const getRandomValues = crypto.getRandomValues.bind(crypto);
  vi.stubGlobal("crypto", { getRandomValues });
  await submitMessage();
  expect(transport.runAgent).toHaveBeenCalledWith(expect.objectContaining({ runId: expect.any(String) }));
});

it("shows preparation failures and preserves the typed message", async () => {
  vi.stubGlobal("crypto", { getRandomValues: () => { throw new Error("Random generation unavailable"); } });
  await submitMessage();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("Random generation unavailable");
  expect(host.querySelector("textarea")?.value).toBe("hi");
  expect(transport.runAgent).not.toHaveBeenCalled();
});
