import { useEffect, useRef } from "react";
import type { EmploymentType, ViewFilters, WorkMode } from "./types";

const modes = [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]] as const;
const types = [["fulltime", "Full-time"], ["parttime", "Part-time"], ["contract", "Contract"], ["temporary", "Temporary"]] as const;

function filterSummary<T extends string>(included: T[], excluded: T[], options: readonly (readonly [T, string])[], fallback: string) {
  const labels = new Map(options);
  const selections = [
    ...included.map((key) => labels.get(key)),
    ...excluded.map((key) => `Not ${labels.get(key)}`),
  ].filter(Boolean);
  return selections.length ? selections.join(", ") : fallback;
}

function FilterChoice<T extends string>({ choice, label, included, excluded, onChange }: {
  choice: T;
  label: string;
  included: T[];
  excluded: T[];
  onChange: (included: T[], excluded: T[]) => void;
}) {
  const isIncluded = included.includes(choice);
  const isExcluded = excluded.includes(choice);
  const state = isIncluded ? "included" : isExcluded ? "excluded" : "neutral";
  const nextState = isIncluded ? "exclude" : isExcluded ? "clear" : "include";
  const cycle = () => {
    if (isIncluded) onChange(included.filter((item) => item !== choice), [...excluded.filter((item) => item !== choice), choice]);
    else if (isExcluded) onChange(included, excluded.filter((item) => item !== choice));
    else onChange([...included, choice], excluded);
  };
  return <div className="filter-choice">
    <button type="button" className={`filter-state ${state}`} aria-label={`${label}: ${state}. Click to ${nextState}.`} title={`Click to ${nextState} ${label}`} onClick={cycle}><span aria-hidden="true">{isIncluded ? "✓" : isExcluded ? "×" : ""}</span></button>
    <span>{label}</span>
  </div>;
}

export function JobViewFilters({ value, onChange, reset, clear }: { value: ViewFilters; onChange: (value: ViewFilters) => void; reset: () => void; clear: () => void }) {
  const root = useRef<HTMLDivElement>(null);
  const update = (patch: Partial<ViewFilters>) => onChange({ ...value, ...patch });
  useEffect(() => {
    const close = (event: PointerEvent | KeyboardEvent) => {
      if (event instanceof KeyboardEvent && event.key !== "Escape") return;
      root.current?.querySelectorAll<HTMLDetailsElement>("details[open]").forEach((menu) => {
        if (event instanceof KeyboardEvent || !menu.contains(event.target as Node)) {
          menu.open = false;
          if (event instanceof KeyboardEvent) menu.querySelector("summary")?.focus();
        }
      });
    };
    document.addEventListener("pointerdown", close);
    document.addEventListener("keydown", close);
    return () => { document.removeEventListener("pointerdown", close); document.removeEventListener("keydown", close); };
  }, []);
  const salary = value.minimumPay === null ? "Salary" : new Intl.NumberFormat(undefined, { style: "currency", currency: value.currency, notation: "compact", maximumFractionDigits: 1 }).format(value.minimumPay) + "+ / " + value.period;
  return <div ref={root} className="mainstream-filters">
    <details className="view-filter"><summary>{filterSummary(value.workModes, value.excludedWorkModes, modes, "Work mode")}</summary><div className="view-filter-options choice-filter-options">
      {modes.map(([mode, label]) => <FilterChoice<WorkMode> key={mode} choice={mode} label={label} included={value.workModes} excluded={value.excludedWorkModes} onChange={(workModes, excludedWorkModes) => update({ workModes, excludedWorkModes })} />)}
      <label><input type="checkbox" checked={value.includeUnknownMode} onChange={(event) => update({ includeUnknownMode: event.target.checked })} />Include unspecified work mode</label>
    </div></details>
    <details className="view-filter"><summary>{filterSummary(value.employmentTypes, value.excludedEmploymentTypes, types, "Job type")}</summary><div className="view-filter-options choice-filter-options">
      {types.map(([type, label]) => <FilterChoice<EmploymentType> key={type} choice={type} label={label} included={value.employmentTypes} excluded={value.excludedEmploymentTypes} onChange={(employmentTypes, excludedEmploymentTypes) => update({ employmentTypes, excludedEmploymentTypes })} />)}
    </div></details>
    <details className="view-filter"><summary>{salary}</summary><div className="view-filter-options">
      <label>Minimum pay ({value.currency}/{value.period})<input type="number" min="0" value={value.minimumPay ?? ""} onChange={(event) => update({ minimumPay: event.target.value === "" ? null : Math.max(0, Number(event.target.value)) })} /></label>
      <label><input type="checkbox" checked={value.includeUnknownPay} onChange={(event) => update({ includeUnknownPay: event.target.checked })} />Include jobs without comparable pay</label>
      <button className="text-button" onClick={reset}>Reset to my preferences</button>
    </div></details>
    <select
      className="clearance-filter"
      aria-label="Clearance requirement"
      title="Filter by jobs that require a security clearance or Public Trust"
      value={value.clearanceMode}
      onChange={(event) => update({ clearanceMode: event.target.value as ViewFilters["clearanceMode"] })}
    >
      <option value="all">Any clearance</option>
      <option value="exclude">No clearance</option>
      <option value="only">Clearance only</option>
    </select>
    <button className="text-button clear-job-filters" onClick={clear}>Clear</button>
  </div>;
}
