import { useEffect, useRef } from "react";
import type { ViewFilters } from "./types";

const modes = [["remote", "Remote"], ["hybrid", "Hybrid"], ["onsite", "On-site"]] as const;
const types = [["fulltime", "Full-time"], ["parttime", "Part-time"], ["contract", "Contract"], ["temporary", "Temporary"]] as const;

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
    <details className="view-filter"><summary>{value.workModes.length ? value.workModes.map((mode) => modes.find(([key]) => key === mode)?.[1]).join(" + ") : "Work mode"}</summary><div className="view-filter-options">
      {modes.map(([mode, label]) => <label key={mode}><input type="checkbox" checked={value.workModes.includes(mode)} onChange={() => update({ workModes: value.workModes.includes(mode) ? value.workModes.filter((item) => item !== mode) : [...value.workModes, mode] })} />{label}</label>)}
      <label><input type="checkbox" checked={value.includeUnknownMode} onChange={(event) => update({ includeUnknownMode: event.target.checked })} />Include unspecified work mode</label>
    </div></details>
    <details className="view-filter"><summary>{value.employmentTypes.length ? value.employmentTypes.map((type) => types.find(([key]) => key === type)?.[1]).join(", ") : "Job type"}</summary><div className="view-filter-options">
      {types.map(([type, label]) => <label key={type}><input type="checkbox" checked={value.employmentTypes.includes(type)} onChange={() => update({ employmentTypes: value.employmentTypes.includes(type) ? value.employmentTypes.filter((item) => item !== type) : [...value.employmentTypes, type] })} />{label}</label>)}
    </div></details>
    <details className="view-filter"><summary>{salary}</summary><div className="view-filter-options">
      <label>Minimum pay ({value.currency}/{value.period})<input type="number" min="0" value={value.minimumPay ?? ""} onChange={(event) => update({ minimumPay: event.target.value === "" ? null : Math.max(0, Number(event.target.value)) })} /></label>
      <label><input type="checkbox" checked={value.includeUnknownPay} onChange={(event) => update({ includeUnknownPay: event.target.checked })} />Include jobs without comparable pay</label>
      <button className="text-button" onClick={reset}>Reset to my preferences</button>
    </div></details>
    <button className="text-button clear-job-filters" onClick={clear}>Clear</button>
  </div>;
}
