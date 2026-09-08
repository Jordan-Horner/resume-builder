// @vitest-environment jsdom
import { act } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { JobViewFilters } from "./JobViewFilters";
import { EMPTY_VIEW } from "./viewPreferences";
import type { ViewFilters } from "./types";

let host: HTMLDivElement;
let root: Root;
let value: ViewFilters;

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  value = { ...EMPTY_VIEW };
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.restoreAllMocks();
});

async function renderFilters() {
  const render = () => root.render(<JobViewFilters value={value} onChange={(next) => { value = next; render(); }} reset={() => undefined} clear={() => undefined} />);
  await act(async () => render());
}

async function press(label: string) {
  await act(async () => ([...host.querySelectorAll("button")].find((button) => button.getAttribute("aria-label")?.startsWith(`${label}:`)) as HTMLButtonElement).click());
}

it("switches each job type between neutral, excluded, and included", async () => {
  await renderFilters();

  await press("Contract");
  expect(value.employmentTypes).toEqual(["contract"]);
  expect(value.excludedEmploymentTypes).toEqual([]);

  await press("Contract");
  expect(value.employmentTypes).toEqual([]);
  expect(value.excludedEmploymentTypes).toEqual(["contract"]);
  expect(host.querySelectorAll("summary")[1].textContent).toBe("Not Contract");

  await press("Contract");
  expect(value.excludedEmploymentTypes).toEqual([]);
});

it("supports excluded work modes independently from included modes", async () => {
  await renderFilters();

  await press("Remote");
  await press("On-site");
  await press("On-site");

  expect(value.workModes).toEqual(["remote"]);
  expect(value.excludedWorkModes).toEqual(["onsite"]);
  expect(host.querySelector("summary")?.textContent).toBe("Remote, Not On-site");
});
