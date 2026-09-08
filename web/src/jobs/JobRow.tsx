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
  const isHot = job.personalization?.hot === true;
  return (
    <button className={selected ? "job-row selected" : "job-row"} onClick={(event) => onOpen(event.currentTarget)}>
      <span className="job-row-main">
        <span className="job-title-line">
          <strong>{job.title}</strong>
          {isHot && <span className="job-hot-status">Hot</span>}
        </span>
        <span className="company-line">
          <span className="company">{job.company}</span>
          {job.company_recognition?.top_workplace && <span className="recognition-badge top-workplace">Top workplace</span>}
          {job.company_recognition?.major_employer && <span className="recognition-badge major-employer">Major employer</span>}
        </span>
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
