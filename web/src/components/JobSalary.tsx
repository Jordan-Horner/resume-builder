import { useEffect, useState } from "react";
import { estimateJobSalary, getSavedJobSalary } from "../api";
import type { Job, SalaryEstimateResult } from "../types";

type Pay = Pick<Job, "salary_min" | "salary_max" | "salary_currency" | "salary_interval">;

const pendingSalaryEstimates = new Map<string, Promise<SalaryEstimateResult>>();

function ongoingSalaryEstimate(jobId: string) {
  const existing = pendingSalaryEstimates.get(jobId);
  if (existing) return existing;
  const request = estimateJobSalary(jobId);
  pendingSalaryEstimates.set(jobId, request);
  const clear = () => {
    if (pendingSalaryEstimates.get(jobId) === request) pendingSalaryEstimates.delete(jobId);
  };
  void request.then(clear, clear);
  return request;
}

function formatPay(pay: Pay) {
  const yearly = pay.salary_interval === "yearly" || pay.salary_interval === "year";
  const format = (amount: number) => new Intl.NumberFormat(undefined, {
    style: "currency",
    currency: pay.salary_currency || "USD",
    notation: yearly ? "compact" : "standard",
    maximumFractionDigits: yearly ? 0 : 2,
  }).format(amount);
  const amounts = [pay.salary_min, pay.salary_max].filter((amount): amount is number => amount !== null);
  const period = pay.salary_interval === "hourly" ? "hour" : pay.salary_interval === "yearly" ? "year" : pay.salary_interval;
  return `${amounts.map(format).join("–")}${period ? ` / ${period}` : ""}`;
}

export function JobSalary({ job }: { job: Job }) {
  const [result, setResult] = useState<SalaryEstimateResult | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const posted = job.salary_min !== null || job.salary_max !== null;
  const [checkingSaved, setCheckingSaved] = useState(!posted);

  useEffect(() => {
    let active = true;
    if (posted) return () => { active = false; };
    const pending = pendingSalaryEstimates.get(job.id);
    if (pending) setBusy(true);
    else setCheckingSaved(true);
    (pending || getSavedJobSalary(job.id))
      .then((value) => {
        if (!active || !value) return;
        if (value.job_id !== job.id) throw new Error("Could not load the saved salary estimate for this job.");
        setResult(value);
      })
      .catch((reason: unknown) => {
        if (!active) return;
        setError(reason instanceof Error ? reason.message : "Could not load the saved salary estimate.");
      })
      .finally(() => {
        if (!active) return;
        if (pending) setBusy(false);
        else setCheckingSaved(false);
      });
    return () => { active = false; };
  }, [job.id, posted]);

  async function requestEstimate() {
    if (busy || checkingSaved || posted) return;
    setBusy(true);
    setError("");
    try {
      const value = await ongoingSalaryEstimate(job.id);
      if (value.job_id !== job.id) throw new Error("Could not load the salary estimate for this job.");
      setResult(value);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not estimate salary. Try again.");
    } finally {
      setBusy(false);
    }
  }

  if (posted) return <span>{formatPay(job)}</span>;
  if (result?.status === "posted" && result.posted_salary) return <span>{formatPay(result.posted_salary)}</span>;
  const estimate = result?.estimate;
  if (result?.status === "estimated" && estimate) {
    const pay = formatPay({ salary_min: estimate.minimum, salary_max: estimate.maximum, salary_currency: estimate.currency, salary_interval: estimate.period });
    const confidence = estimate.confidence === "medium" ? "Medium" : "Low";
    return <details className="salary-result" aria-live="polite">
      <summary><span className="salary-result-prefix">Est.</span> {pay}<span className="salary-result-confidence">{confidence}</span></summary>
      <div className="salary-result-popover">
        <strong>{confidence} confidence</strong>
        <p>Not employer-confirmed. {estimate.reasoning}</p>
        <p>{estimate.company_basis}</p>
        {estimate.assumptions.length > 0 && <ul>{estimate.assumptions.map((assumption, index) => <li key={index}>{assumption}</li>)}</ul>}
      </div>
    </details>;
  }
  if (result?.status === "unavailable") return <details className="salary-result salary-result-unavailable" role="status">
    <summary>Estimate unavailable</summary>
    <div className="salary-result-popover"><p>{estimate?.reasoning || "There isn’t enough information to estimate this salary."}</p></div>
  </details>;
  return <div className="salary-request" aria-live="polite">
    <button className="salary-tag-button estimate-salary-button" type="button" disabled={busy || checkingSaved} onClick={() => void requestEstimate()}>
      <span className="salary-tag-action">{busy ? "Estimating…" : checkingSaved ? "Loading estimate…" : error ? "Try Again" : "Estimate Salary"}</span>
    </button>
    {error && <p className="salary-request-error" role="alert">{error}</p>}
  </div>;
}
