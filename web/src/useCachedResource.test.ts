// @vitest-environment jsdom
import { act, createElement } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { __resetCachedResources, useCachedResource } from "./useCachedResource";

let host: HTMLDivElement;
let root: Root;
let latest: ReturnType<typeof useCachedResource<string[]>> | null;

function Probe({ fetcher }: { fetcher: () => Promise<string[]> }) {
  latest = useCachedResource<string[]>("probe", fetcher);
  return null;
}

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  __resetCachedResources();
  latest = null;
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
});

it("shows a loading state on first mount, then caches the resolved value for the next mount", async () => {
  const fetcher = vi.fn().mockResolvedValue(["a"]);

  await act(async () => root.render(createElement(Probe, { fetcher })));
  expect(latest?.data).toEqual(["a"]);
  expect(fetcher).toHaveBeenCalledTimes(1);

  await act(async () => root.unmount());
  root = createRoot(host);
  const secondFetcher = vi.fn().mockResolvedValue(["a", "b"]);
  await act(async () => root.render(createElement(Probe, { fetcher: secondFetcher })));

  // The cached value from the first mount renders instantly...
  expect(latest?.loading).toBe(false);
  // ...while a background refetch keeps it current.
  expect(secondFetcher).toHaveBeenCalledTimes(1);
  expect(latest?.data).toEqual(["a", "b"]);
});

it("surfaces an error only when there is no cached value to fall back on", async () => {
  const failing = vi.fn().mockRejectedValue(new Error("network down"));
  await act(async () => root.render(createElement(Probe, { fetcher: failing })));
  expect(latest?.error).toBe("network down");
  expect(latest?.loading).toBe(false);
});

it("does not clobber cached content when a background revalidation fails", async () => {
  const succeeding = vi.fn().mockResolvedValue(["a"]);
  await act(async () => root.render(createElement(Probe, { fetcher: succeeding })));

  await act(async () => root.unmount());
  root = createRoot(host);
  const failing = vi.fn().mockRejectedValue(new Error("network down"));
  await act(async () => root.render(createElement(Probe, { fetcher: failing })));

  expect(latest?.data).toEqual(["a"]);
  expect(latest?.error).toBe("");
});

it("reload() refetches and updates the cache", async () => {
  const fetcher = vi.fn().mockResolvedValueOnce(["a"]).mockResolvedValueOnce(["a", "b"]);
  await act(async () => root.render(createElement(Probe, { fetcher })));
  expect(latest?.data).toEqual(["a"]);

  await act(() => latest?.reload());
  expect(fetcher).toHaveBeenCalledTimes(2);
  expect(latest?.data).toEqual(["a", "b"]);
});
