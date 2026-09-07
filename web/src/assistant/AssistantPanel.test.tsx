// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { beforeEach, afterEach, expect, it, vi } from "vitest";
import AssistantPanel from "./AssistantPanel";
import { assistantRequest, type Conversation } from "./api";

vi.mock("./api", () => ({ assistantRequest: vi.fn() }));
let host: HTMLDivElement;
let root: Root;
const thread: Conversation = {
  id: "saved", resume_id: "resumes/baselines/support.md", job_id: null, title: "Improve summary",
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
it("renders a resume-removal confirmation separately from wording", async () => {
  const removal = { ...thread, proposals: [{ id: "remove", status: "pending", message: "", payload: {
    kind: "resume_removal" as const, resume_id: "resumes/baselines/support.md", name: "Support",
    revision: "abc", application_references: [], vault_unchanged: true as const,
    tailored_resumes_unchanged: true as const,
  } }] };
  vi.mocked(assistantRequest).mockImplementation(async (path) => path === "/status"
    ? { configured: true, online: true }
    : path === "/threads" ? { threads: [removal] } : removal);
  await act(async () => root.render(<AssistantPanel open target={null} onClose={() => undefined} />));
  expect(host.textContent).toContain("Remove this directional résumé?");
  expect(host.textContent).toContain("Career-vault evidence and tailored résumés stay unchanged.");
  await act(async () => Array.from(host.querySelectorAll("button")).find((b) => b.textContent === "Remove résumé")?.click());
  expect(assistantRequest).toHaveBeenCalledWith("/threads/saved/proposals/remove/accept", { method: "POST" });
});
it("renders a job-preference confirmation separately from resume wording", async () => {
  const preference = { ...thread, proposals: [{ id: "preference", status: "pending", message: "", payload: {
    kind: "job_preference" as const, direction: "avoid" as const, action: "add" as const,
    statement: "Phone-first support", confirmation_hash: "hash",
  } }] };
  vi.mocked(assistantRequest).mockImplementation(async (path) => path === "/status"
    ? { configured: true, online: true }
    : path === "/threads" ? { threads: [preference] } : preference);
  await act(async () => root.render(<AssistantPanel open target={null} onClose={() => undefined} />));
  expect(host.textContent).toContain("Avoid this kind of work?");
  expect(host.textContent).toContain("Phone-first support");
  await act(async () => Array.from(host.querySelectorAll("button")).find((button) => button.textContent === "Save preference")?.click());
  expect(assistantRequest).toHaveBeenCalledWith("/threads/saved/proposals/preference/accept", { method: "POST" });
});
it("renders assistant markdown as readable, safe content", async () => {
  const markdownThread = {
    ...thread,
    messages: [{
      id: "markdown-reply",
      role: "assistant" as const,
      content: "I can help with:\n\n- **Reviewing your résumé**\n- `Checking job matches`\n\n<script>alert('unsafe')</script>",
    }],
  };
  vi.mocked(assistantRequest).mockImplementation(async (path) => path === "/status"
    ? { configured: true, online: true }
    : path === "/threads" ? { threads: [markdownThread] } : markdownThread);
  await act(async () => root.render(<AssistantPanel open target={null} onClose={() => undefined} />));
  expect(host.querySelectorAll(".assistant-markdown li")).toHaveLength(2);
  expect(host.querySelector(".assistant-markdown strong")?.textContent).toBe("Reviewing your résumé");
  expect(host.querySelector(".assistant-markdown code")?.textContent).toBe("Checking job matches");
  expect(host.querySelector(".assistant-markdown script")).toBeNull();
});
it("does not silently switch the attached resume", async () => {
  await act(async () => root.render(<AssistantPanel open target={{ kind: "resume", id: "resumes/baselines/cloud.md", name: "Cloud", nonce: 1 }} onClose={() => undefined} />));
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
  expect(assistantRequest).toHaveBeenCalledWith("/threads/saved/runs", {
    method: "POST",
    body: expect.stringContaining('"prompt":"hi"'),
  });
});

it("shows preparation failures and preserves the typed message", async () => {
  vi.stubGlobal("crypto", { getRandomValues: () => { throw new Error("Random generation unavailable"); } });
  await submitMessage();
  expect(host.querySelector('[role="alert"]')?.textContent).toContain("Random generation unavailable");
  expect(host.querySelector("textarea")?.value).toBe("hi");
  expect(assistantRequest).not.toHaveBeenCalledWith("/threads/saved/runs", expect.anything());
});

it("does not poll a closed assistant", async () => {
  vi.useFakeTimers();
  try {
    await act(async () => root.render(<AssistantPanel open={false} target={null} onClose={() => undefined} />));
    vi.mocked(assistantRequest).mockClear();
    await act(async () => vi.advanceTimersByTimeAsync(12000));
    expect(assistantRequest).not.toHaveBeenCalledWith("/threads/saved");
  } finally {
    vi.useRealTimers();
  }
});
