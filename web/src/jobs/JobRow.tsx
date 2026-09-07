import { ArrowIcon } from "../components";
import type { Job } from "../types";
import { formatPayRange, formatShortDate, formatWorkModes } from "./jobFormatters";

interface Props {
  job: Job;
  selected: boolean;
  onOpen: (origin: HTMLButtonElement) => void;
}

export function JobRow({ job, selected, onOpen }: Props) {
  const salary = formatPayRange(job);
  const screenLabel = job.quick_screen?.status === "complete"
    ? `Screened: ${job.quick_screen.label === "Unknown" ? "Unclear" : job.quick_screen.label}`
    : job.quick_screen?.status === "skipped"
      ? "Not screened"
      : job.quick_screen?.status === "failed" ? "Screen failed" : "Not screened";
  const screenTitle = job.quick_screen?.status === "complete"
    ? "A background quick screen completed for this job."
    : job.quick_screen?.status === "skipped"
      ? `Automatic screening skipped this job: ${job.quick_screen.label}.`
      : job.quick_screen?.status === "failed"
        ? "The automatic screen could not finish. Open the job to try again."
        : "This job has not been quick-screened.";
  const screenState = job.quick_screen?.status === "complete"
    ? "complete"
    : job.quick_screen?.status === "failed" ? "failed" : "unscreened";
  return (
    <button className={selected ? "job-row selected" : "job-row"} onClick={(event) => onOpen(event.currentTarget)}>
      <span className="job-row-main">
        <span className="job-title-line"><strong>{job.title}</strong></span>
        <span className="company">{job.company}</span>
        <span className="job-meta"><span>{job.location}</span><i /><span>{formatWorkModes(job.work_modes)}</span><i /><span className={`job-screen-state ${screenState}`} title={screenTitle}>{screenLabel}</span></span>
      </span>
      <span className="job-row-side">
        {salary && <span className="row-salary">{salary}</span>}
        <span>{formatShortDate(job.posted_at || job.first_seen_at)}</span>
        <ArrowIcon />
      </span>
    </button>
  );
}
