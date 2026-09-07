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
    ? [job.quick_screen.label, job.quick_screen.resume_name].filter(Boolean).join(" · ")
    : job.quick_screen?.status === "skipped"
      ? `Skipped · ${job.quick_screen.label}`
      : job.quick_screen?.status === "failed" ? "Screen unavailable" : "";
  const screenTitle = job.quick_screen?.status === "failed"
    ? "The automatic screen could not finish. Open the job to try again."
    : "Quick-screen status";
  return (
    <button className={selected ? "job-row selected" : "job-row"} onClick={(event) => onOpen(event.currentTarget)}>
      <span className="job-row-main">
        <span className="job-title-line"><strong>{job.title}</strong>{job.personalization?.hot && <span className="job-hot-status">Hot</span>}{screenLabel && <span className={`job-screen-status ${job.quick_screen?.status}`} title={screenTitle}>{screenLabel}</span>}</span>
        <span className="company">{job.company}</span>
        <span className="job-meta"><span>{job.location}</span><i /><span>{formatWorkModes(job.work_modes)}</span></span>
      </span>
      <span className="job-row-side">
        {salary && <span className="row-salary">{salary}</span>}
        <span>{formatShortDate(job.posted_at || job.first_seen_at)}</span>
        <ArrowIcon />
      </span>
    </button>
  );
}
