// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from "vitest";
import { EMPTY_FILTERS, EMPTY_VIEW, persistView, restoreView, VIEW_KEY } from "./viewPreferences";

const defaults = { ...EMPTY_VIEW, workModes: ["remote" as const, "hybrid" as const], minimumPay: 100000 };
describe("onboarding filter defaults", () => {
  beforeEach(() => localStorage.clear());
  it("applies onboarding defaults on first visit", () => {
    expect(restoreView(defaults).filters.view).toEqual(defaults);
  });
  it("preserves customized fields while following updated defaults", () => {
    persistView({ ...EMPTY_FILTERS, view: { ...defaults, minimumPay: 80000 } }, defaults);
    const restored = restoreView({ ...defaults, minimumPay: 110000, country: "Canada" });
    expect(restored.filters.view?.minimumPay).toBe(80000);
    expect(restored.filters.view?.country).toBe("Canada");
    expect(restored.updated).toBe(true);
  });
  it("preserves clear filters across reload", () => {
    persistView(EMPTY_FILTERS, defaults);
    expect(restoreView(defaults).filters).toEqual(EMPTY_FILTERS);
  });
  it("migrates legacy filters without adding role restrictions", () => {
    localStorage.setItem("resume-builder.job-filters.v1", JSON.stringify({search: "Acme", workMode: "hybrid", dateDays: 7, employmentType: "contract"}));
    const result = restoreView(defaults).filters;
    expect(result.search).toBe("Acme");
    expect(result.view?.workModes).toEqual(["hybrid"]);
    expect(result.view?.roles).toEqual(defaults.roles);
    expect(result.view?.employmentTypes).toEqual(["contract"]);
  });
  it("surfaces corrupted saved state", () => {
    localStorage.setItem(VIEW_KEY, "{}");
    expect(() => restoreView(defaults)).toThrow();
  });
  it("removes v2 roles and preserves the visible location without losing other choices", () => {
    localStorage.setItem("resume-builder.job-view.v2", JSON.stringify({ filters: { ...EMPTY_FILTERS, search: "support", view: { ...defaults, roles: ["Support Engineer"], country: "United States", locations: ["Boston"], minimumPay: 80000 } }, previous: defaults }));
    const restored = restoreView(defaults).filters;
    expect(restored.view?.roles).toEqual([]);
    expect(restored.view?.locations).toEqual(["Boston"]);
    expect(restored.view?.country).toBe(defaults.country);
    expect(restored.view?.minimumPay).toBe(80000);
    expect(restored.search).toBe("support");
  });
  it("prefills onboarding country when migrating the previously empty v3 location", () => {
    localStorage.setItem("resume-builder.job-view.v3", JSON.stringify({filters: EMPTY_FILTERS, previous: defaults}));
    expect(restoreView({...defaults, country: "United States"}).filters.view?.country).toBe("United States");
  });
  it("moves a saved v4 city into local narrowing while enforcing the saved country", () => {
    localStorage.setItem("resume-builder.job-view.v4", JSON.stringify({filters: {...EMPTY_FILTERS, view: {...EMPTY_VIEW, country: "Boston"}}, previous: {...defaults, country: "United States"}}));
    const restored = restoreView({...defaults, country: "United States"}).filters.view;
    expect(restored?.country).toBe("United States");
    expect(restored?.locations).toEqual(["Boston"]);
  });
});
