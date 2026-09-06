import { useEffect, useRef, useState } from "react";
import { getResumeRecommendation, getSavedJobScreen, screenJob } from "../api";
import { ArrowIcon, IconButton } from "../components";
import { JobSalary } from "../components/JobSalary";
import { useAssistant } from "../assistant/AssistantProvider";
import type { Job, JobScreenResult, ResumeRecommendation } from "../types";
import { formatPayRange, formatWorkModes } from "./jobFormatters";

interface Props {
  job: Job;
  companyBlocked: boolean;
  companyBusy: boolean;
  pendingAction: "not-interested" | "applied" | null;
  queueLoading: boolean;
  onClose: () => void;
  onChangeCompany: (company: string, blocked: boolean) => Promise<void>;
  onDisposition: (disposition: "not-interested" | "applied") => Promise<void>;
}

const criterionOutcomeLabels = {
  supported: "Supported",
  partially_supported: "Partially supported",
  transferable: "Transferable experience",
  unknown: "Not enough evidence",
  apparent_gap: "Possible gap",
} as const;

export function JobDetailPanel({
  job,
  companyBlocked,
  companyBusy,
  pendingAction,
  queueLoading,
  onClose,
  onChangeCompany,
  onDisposition,
}: Props) {
  const assistant = useAssistant();
  const heading = useRef<HTMLHeadingElement>(null);
  const [recommendation, setRecommendation] = useState<ResumeRecommendation | null>(null);
  const [recommendationError, setRecommendationError] = useState("");
  const [jobScreen, setJobScreen] = useState<JobScreenResult | null>(null);
  const [screening, setScreening] = useState(false);
  const [screenError, setScreenError] = useState("");

  useEffect(() => {
    if (window.matchMedia?.("(max-width: 900px)").matches) heading.current?.focus();
  }, [job.id]);

  useEffect(() => {
    let active = true;
    setRecommendation(null);
    setRecommendationError("");
    setJobScreen(null);
    setScreenError("");
    void Promise.allSettled([getResumeRecommendation(job.id), getSavedJobScreen(job.id)]).then(([resumeResult, screenResult]) => {
      if (!active) return;
      if (resumeResult.status === "fulfilled") setRecommendation(resumeResult.value);
      else setRecommendationError(resumeResult.reason instanceof Error ? resumeResult.reason.message : "Could not load the resume recommendation.");
      if (screenResult.status === "fulfilled") setJobScreen(screenResult.value);
      else setScreenError(screenResult.reason instanceof Error ? screenResult.reason.message : "Could not load this job screen.");
    });
    return () => { active = false; };
  }, [job.id]);

  async function runJobScreen() {
    if (screening) return;
    setScreening(true);
    setScreenError("");
    try { setJobScreen(await screenJob(job.id)); }
    catch (reason) { setScreenError(reason instanceof Error ? reason.message : "Could not screen this job."); }
    finally { setScreening(false); }
  }

  const postedSalary = formatPayRange(job);
  const contextName = `${job.title} at ${job.company}`;
  return (
    <aside className="job-detail" aria-labelledby="selected-job-title">
      <div className="detail-summary">
        <IconButton className="detail-close" onClick={onClose} label="Close job details">×</IconButton>
        <p className="eyebrow">{job.providers.join(" · ") || "Job listing"}</p>
        <h2 id="selected-job-title" ref={heading} tabIndex={-1}>{job.title}</h2>
        <div className="detail-company-actions">
          <p className="detail-company">{job.company}</p>
          <button className="secondary-button" disabled={companyBusy || !!pendingAction || queueLoading || !job.company.trim()} onClick={() => void onChangeCompany(job.company, !companyBlocked)}>
            {companyBusy ? "Saving…" : companyBlocked ? "Unblock company" : "Block company"}
          </button>
        </div>
        <div className="detail-tags">
          <span>{formatWorkModes(job.work_modes)}</span>
          <span>{job.location}</span>
          {postedSalary ? <span>{postedSalary}</span> : <JobSalary key={job.id} job={job} />}
        </div>
        {recommendation?.recommended_resume && <div className="resume-recommendation">
          <span>Recommended resume</span>
          <strong>{recommendation.recommended_resume.name}</strong>
          {recommendation.match && <em>{recommendation.match.label}</em>}
        </div>}
        {recommendation?.status === "unavailable" && recommendation.message && <p className="recommendation-empty">{recommendation.message}</p>}
        {recommendationError && <p className="recommendation-error" role="status">{recommendationError}</p>}
        <section className="job-screen-card" aria-label="Job screen">
          {jobScreen ? <>
            <div className="job-screen-heading"><span>{jobScreen.result.screening_label}</span><strong>{jobScreen.result.fit_label}</strong><em>{jobScreen.result.eligibility_label}{jobScreen.result.screening_label === "Quick screen" ? ` · ${jobScreen.result.confidence} confidence` : ""}</em></div>
            <p>{jobScreen.result.reasoning_summary}</p>
            {jobScreen.result.evidence_used.length > 0 && <p className="job-screen-coverage">Based on {jobScreen.result.evidence_used.length} verified career {jobScreen.result.evidence_used.length === 1 ? "fact" : "facts"}.</p>}
            {jobScreen.result.evidence_strategy === "criterion-driven" && jobScreen.result.criterion_evidence && <p className="job-screen-coverage">Checked {jobScreen.result.criterion_evidence.filter((item) => item.status !== "not-resume-evaluable").length} role criteria against your career evidence.</p>}
            {jobScreen.result.posting_coverage === "partial" && <p className="job-screen-warning">This posting exceeded the quick-screen limit, so the result uses partial posting context.</p>}
            {(jobScreen.result.strengths.length > 0 || jobScreen.result.gaps.length > 0 || jobScreen.result.unknowns.length > 0 || (jobScreen.result.criterion_assessments?.length ?? 0) > 0) && <details className="job-screen-evidence">
              <summary>Screening details</summary>
              {jobScreen.result.criterion_assessments && jobScreen.result.criterion_assessments.length > 0 && <div><strong>Role criteria</strong><ul>{jobScreen.result.criterion_assessments.map((assessment) => {
                const criterion = jobScreen.result.criterion_evidence?.find((item) => item.criterion_id === assessment.criterion_id);
                return <li key={assessment.criterion_id}><strong>{criterion?.label ?? assessment.criterion_id}: {criterionOutcomeLabels[assessment.outcome]}</strong><span>{assessment.explanation}</span></li>;
              })}</ul></div>}
              {jobScreen.result.strengths.length > 0 && <div><strong>Strengths</strong><ul>{jobScreen.result.strengths.map((item) => <li key={item}>{item}</li>)}</ul></div>}
              {jobScreen.result.gaps.length > 0 && <div><strong>Gaps</strong><ul>{jobScreen.result.gaps.map((item) => <li key={item}>{item}</li>)}</ul></div>}
              {jobScreen.result.unknowns.length > 0 && <div><strong>Unknowns</strong><ul>{jobScreen.result.unknowns.map((item) => <li key={item}>{item}</li>)}</ul></div>}
              {jobScreen.result.evidence_strategy === "criterion-driven" && jobScreen.result.criterion_evidence && !jobScreen.result.criterion_assessments?.length && <div><strong>Criteria checked</strong><ul>{jobScreen.result.criterion_evidence.filter((item) => item.status !== "not-resume-evaluable").map((item) => <li key={item.criterion_id}>{item.label}: {item.status === "demonstrated-candidate" ? "work evidence found" : item.status === "supporting-candidate" ? "supporting evidence found" : "no relevant evidence retrieved"}</li>)}</ul></div>}
            </details>}
            {jobScreen.result.evidence_used.length > 0 && <details className="job-screen-evidence job-screen-facts">
              <summary>Evidence used</summary>
              <ul>{jobScreen.result.evidence_used.map((item) => <li key={item.fact_id}><strong>{item.title}</strong><span>{item.strength}</span></li>)}</ul>
            </details>}
            <div className="job-screen-actions"><button className="text-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening…" : "Refresh screen"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : <>
            <div><strong>No quick screen yet</strong><p>Run the inexpensive first pass for eligibility and résumé fit. Deeper company research is separate.</p></div>
            <div className="job-screen-actions"><button className="secondary-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening job…" : "Screen job"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </>}
          {screenError && <p className="recommendation-error" role="alert">{screenError}</p>}
        </section>
        <div className="job-actions" aria-label="Update job status">
          {job.url && <a className="secondary-button original-link" href={job.url} target="_blank" rel="noreferrer">Open posting <ArrowIcon /></a>}
          <button className="primary-button apply-button" onClick={() => void onDisposition("applied")} disabled={pendingAction !== null}>
            {pendingAction === "applied" ? "Moving to Applications…" : "Mark as applied"}
          </button>
          <button className="secondary-button reject-button" onClick={() => void onDisposition("not-interested")} disabled={pendingAction !== null}>
            {pendingAction === "not-interested" ? "Removing…" : "Not interested"}
          </button>
        </div>
      </div>
      <div className="job-description">
        {job.description ? job.description.split(/\n+/).map((paragraph, index) => paragraph.trim() && <p key={index}>{paragraph}</p>) : <p>No description was included with this listing.</p>}
      </div>
    </aside>
  );
}
