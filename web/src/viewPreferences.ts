import type { JobFilters, ViewFilters } from "./types";
import { loadJobFilters } from "./jobFilterPreferences";

export const VIEW_KEY = "resume-builder.job-view.v7";
export const EMPTY_VIEW: ViewFilters = { roles: [], workModes: [], country: "", locations: [], employmentTypes: [], minimumPay: null, currency: "USD", period: "year", includeUnknownPay: true, includeUnknownMode: true, includeUnmatchedLocation: false, clearanceMode: "all" };
export const EMPTY_FILTERS: JobFilters = { search: "", dateDays: 0, workMode: "", employmentType: "", view: EMPTY_VIEW };

function normalizeStoredView(value: unknown): ViewFilters {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Saved filters are invalid. Your job preferences have been restored.");
  const candidate = { ...(value as Record<string, unknown>) };
  if (candidate.clearanceMode === undefined) {
    if (candidate.includeClearanceJobs !== undefined && typeof candidate.includeClearanceJobs !== "boolean") throw new Error("Saved filters are invalid. Your job preferences have been restored.");
    candidate.clearanceMode = candidate.includeClearanceJobs === false ? "exclude" : "all";
  }
  delete candidate.includeClearanceJobs;
  return candidate as unknown as ViewFilters;
}

export function restoreView(defaults: ViewFilters): { filters: JobFilters; previous: ViewFilters; updated?: boolean } {
  const migrating = !localStorage.getItem(VIEW_KEY);
  const raw = localStorage.getItem(VIEW_KEY) || localStorage.getItem("resume-builder.job-view.v6") || localStorage.getItem("resume-builder.job-view.v5") || localStorage.getItem("resume-builder.job-view.v4") || localStorage.getItem("resume-builder.job-view.v3") || localStorage.getItem("resume-builder.job-view.v2");
  if (!raw) {
    const legacy = loadJobFilters();
    return { filters: { ...legacy, workMode: "", employmentType: "", view: { ...defaults, ...(legacy.workMode ? { workModes: [legacy.workMode] } : {}), ...(legacy.employmentType ? { employmentTypes: [legacy.employmentType] } : {}) } }, previous: defaults };
  }
  const saved = JSON.parse(raw) as { filters: JobFilters; previous: unknown };
  if (!saved.filters?.view || !saved.previous) throw new Error("Saved filters could not be restored. Use Reset to my preferences.");
  const candidate = normalizeStoredView(saved.filters.view);
  const previous = normalizeStoredView(saved.previous);
  if (![candidate.roles, candidate.locations, candidate.workModes, candidate.employmentTypes].every((items) => Array.isArray(items) && items.every((item) => typeof item === "string")) || typeof candidate.country !== "string" || !/^[A-Z]{3}$/.test(candidate.currency) || !["year", "hour"].includes(candidate.period) || !["all", "exclude", "only"].includes(candidate.clearanceMode) || ![0, 1, 3, 7, 14, 30].includes(saved.filters.dateDays) || typeof saved.filters.search !== "string" || (candidate.minimumPay !== null && (!Number.isFinite(candidate.minimumPay) || candidate.minimumPay < 0))) throw new Error("Saved filters are invalid. Your job preferences have been restored.");
  const view = { ...candidate };
  for (const key of Object.keys(defaults) as (keyof ViewFilters)[]) {
    if (JSON.stringify(view[key]) === JSON.stringify(previous[key])) Object.assign(view, { [key]: defaults[key] });
  }
  view.roles = [];
  if (migrating) {
    const previousLocation = candidate.country.trim();
    const isCountry = !previousLocation || previousLocation.toLowerCase() === (previous.country || "").toLowerCase() || /^(us|usa|u\.s\.?a?\.?|united states(?: of america)?)$/i.test(previousLocation);
    view.locations = isCountry ? candidate.locations : [previousLocation];
  }
  view.country = defaults.country;
  view.includeUnmatchedLocation = false;
  return { filters: { ...saved.filters, view }, previous: defaults, updated: !migrating && JSON.stringify(previous) !== JSON.stringify(defaults) };
}

export function persistView(filters: JobFilters, previous: ViewFilters) {
  localStorage.setItem(VIEW_KEY, JSON.stringify({ filters, previous }));
}
