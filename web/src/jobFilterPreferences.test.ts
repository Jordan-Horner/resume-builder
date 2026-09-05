import { describe, expect, it } from "vitest";
import {
  DEFAULT_JOB_FILTERS,
  JOB_FILTERS_STORAGE_KEY,
  loadJobFilters,
  saveJobFilters,
} from "./jobFilterPreferences";

describe("job filter preferences", () => {
  it("round-trips every job filter", () => {
    const values = new Map<string, string>();
    const storage = {
      getItem: (key: string) => values.get(key) ?? null,
      setItem: (key: string, value: string) => values.set(key, value),
    };
    const filters = {
      search: "support engineer",
      workMode: "remote" as const,
      dateDays: 7 as const,
      employmentType: "fulltime" as const,
    };

    saveJobFilters(filters, storage);

    expect(loadJobFilters(storage)).toEqual(filters);
    expect(values.has(JOB_FILTERS_STORAGE_KEY)).toBe(true);
  });

  it("uses safe defaults for malformed or unsupported saved values", () => {
    const malformed = { getItem: () => "not-json" };
    const unsupported = {
      getItem: () => JSON.stringify({
        search: 42,
        workMode: "somewhere",
        dateDays: 365,
        employmentType: "volunteer",
      }),
    };

    expect(loadJobFilters(malformed)).toEqual(DEFAULT_JOB_FILTERS);
    expect(loadJobFilters(unsupported)).toEqual(DEFAULT_JOB_FILTERS);
  });

  it("continues without failing when browser storage is blocked", () => {
    const blocked = {
      getItem: () => { throw new Error("blocked"); },
      setItem: () => { throw new Error("blocked"); },
    };

    expect(loadJobFilters(blocked)).toEqual(DEFAULT_JOB_FILTERS);
    expect(() => saveJobFilters(DEFAULT_JOB_FILTERS, blocked)).not.toThrow();
  });
});
