import type { Job } from "../types";

export type Pay = Pick<Job, "salary_min" | "salary_max" | "salary_currency" | "salary_interval">;

export function formatShortDate(value: string | null) {
  if (!value) return "Recently found";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently found";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

export function formatPayRange(pay: Pay) {
  const amounts = [pay.salary_min, pay.salary_max].filter((amount): amount is number => amount !== null);
  if (!amounts.length) return null;
  const yearly = pay.salary_interval === "yearly" || pay.salary_interval === "year";
  const format = (amount: number) => new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: pay.salary_currency || "USD",
    notation: yearly || amount >= 100_000 ? "compact" : "standard",
    maximumFractionDigits: yearly || amount >= 100_000 ? 0 : 2,
  }).format(amount);
  const period = pay.salary_interval === "hourly" ? "hour" : pay.salary_interval === "yearly" ? "year" : pay.salary_interval;
  return `${amounts.map(format).join("–")}${period ? ` / ${period}` : ""}`;
}

export function formatWorkModes(modes: string[]) {
  const labels = modes.filter((mode) => mode !== "unknown").map((mode) => (
    mode === "onsite" ? "On-site" : mode[0].toUpperCase() + mode.slice(1)
  ));
  return labels.join(" + ") || "Work mode not listed";
}

export function formatCompactCurrency(value: number, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 0,
  }).format(value);
}
