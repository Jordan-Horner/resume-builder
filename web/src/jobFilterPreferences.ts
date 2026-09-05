import type { EmploymentType, JobFilters, WorkMode } from "./types";

export const JOB_FILTERS_STORAGE_KEY = "resume-builder.job-filters.v1";

export const DEFAULT_JOB_FILTERS: JobFilters = {
  search: "",
  workMode: "",
  dateDays: 0,
  employmentType: "",
};

const WORK_MODES = new Set<WorkMode>(["remote", "hybrid", "onsite"]);
const DATE_RANGES = new Set<JobFilters["dateDays"]>([0, 1, 3, 7, 14, 30]);
const EMPLOYMENT_TYPES = new Set<EmploymentType>(["fulltime", "parttime", "contract", "temporary"]);

export function loadJobFilters(storage: Pick<Storage, "getItem"> = window.localStorage): JobFilters {
  try {
    const saved = JSON.parse(storage.getItem(JOB_FILTERS_STORAGE_KEY) || "null") as Partial<JobFilters> | null;
    if (!saved || typeof saved !== "object") return { ...DEFAULT_JOB_FILTERS };

    return {
      search: typeof saved.search === "string" ? saved.search : "",
      workMode: saved.workMode === "" || WORK_MODES.has(saved.workMode as WorkMode) ? saved.workMode : "",
      dateDays: DATE_RANGES.has(saved.dateDays as JobFilters["dateDays"]) ? saved.dateDays! : 0,
      employmentType: saved.employmentType === "" || EMPLOYMENT_TYPES.has(saved.employmentType as EmploymentType)
        ? saved.employmentType
        : "",
    } as JobFilters;
  } catch {
    return { ...DEFAULT_JOB_FILTERS };
  }
}

export function saveJobFilters(
  filters: JobFilters,
  storage: Pick<Storage, "setItem"> = window.localStorage,
): void {
  try {
    storage.setItem(JOB_FILTERS_STORAGE_KEY, JSON.stringify(filters));
  } catch {
    // Browsing can continue with in-memory filters when storage is unavailable.
  }
}
