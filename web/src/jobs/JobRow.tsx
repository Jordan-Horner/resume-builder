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
  return (
    <button className={selected ? "job-row selected" : "job-row"} onClick={(event) => onOpen(event.currentTarget)}>
      <span className="job-row-main">
        <span className="job-title-line"><strong>{job.title}</strong></span>
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
