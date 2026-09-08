// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { AssistantProvider, useAssistant } from "./AssistantProvider";

vi.mock("./AssistantPanel", () => ({
  default: ({ modal, onClose, target }: { modal: boolean; onClose: () => void; target?: { id?: string; openingQuestion?: string } | null }) => <aside data-modal={modal} data-target={target?.id} data-question={target?.openingQuestion}><button onClick={onClose}>Close panel</button></aside>,
}));

function Harness() {
  const assistant = useAssistant();
  return <><button onClick={() => assistant.discussJob("job-one", "Example job")}>Discuss</button><button onClick={() => assistant.discussJob("job-one", "Example job", "Why was this a miss?")}>Reject Hot</button><button onClick={() => assistant.setWindowContext({ kind: "job", id: "job-two", name: "Next job" })}>Open next job</button></>;
}

let host: HTMLDivElement;
let root: Root;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  vi.stubGlobal("matchMedia", vi.fn(() => ({
    matches: true, media: "(max-width: 480px)", onchange: null,
    addEventListener: vi.fn(), removeEventListener: vi.fn(), addListener: vi.fn(), removeListener: vi.fn(),
    dispatchEvent: vi.fn(),
  })));
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

it("passes a Hot rejection question into the existing assistant", async () => {
  await act(async () => root.render(<AssistantProvider><Harness /></AssistantProvider>));

  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Reject Hot")?.click());

  expect(host.querySelector("[data-question]")?.getAttribute("data-question")).toBe("Why was this a miss?");
});

it("tracks a newly visible job without requiring another assistant action", async () => {
  await act(async () => root.render(<AssistantProvider><Harness /></AssistantProvider>));
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Discuss")?.click());
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Open next job")?.click());

  expect(host.querySelector("[data-target]")?.getAttribute("data-target")).toBe("job-two");
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.unstubAllGlobals();
});

it("makes the background inert on phones and restores focus after closing", async () => {
  await act(async () => root.render(<AssistantProvider><Harness /></AssistantProvider>));
  const trigger = [...host.querySelectorAll("button")].find((button) => button.textContent === "Discuss")!;
  trigger.focus();

  await act(async () => trigger.click());

  expect(host.querySelector(".assistant-workspace")?.hasAttribute("inert")).toBe(true);
  expect(host.querySelector("[data-modal=true]")).not.toBeNull();
  await act(async () => [...host.querySelectorAll("button")].find((button) => button.textContent === "Close panel")?.click());
  await act(async () => new Promise<void>((resolve) => requestAnimationFrame(() => resolve())));

  expect(document.activeElement).toBe(trigger);
});
