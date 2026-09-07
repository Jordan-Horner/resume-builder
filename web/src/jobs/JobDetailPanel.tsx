import { useEffect, useRef, useState } from "react";
import { getJob, getJobFeedback, getJobScreenStatus, getResumeRecommendation, recordJobPostingOpened, screenJob } from "../api";
import { ArrowIcon, IconButton } from "../components";
import { JobSalary } from "../components/JobSalary";
import { useAssistant } from "../assistant/AssistantProvider";
import type { Job, JobFeedback, JobFeedbackAction, JobScreenResult, ResumeRecommendation } from "../types";
import { formatPayRange, formatWorkModes } from "./jobFormatters";

interface Props {
  job: Job;
  companyBlocked: boolean;
  companyBusy: boolean;
  pendingAction: JobFeedbackAction | "applied" | null;
  queueLoading: boolean;
  onClose: () => void;
  onChangeCompany: (company: string, blocked: boolean) => Promise<void>;
  onDisposition: (disposition: JobFeedbackAction | "applied") => Promise<JobFeedback | null>;
  onScreened: (screen: JobScreenResult) => void;
}

const criterionOutcomeLabels = {
  supported: "Supported",
  partially_supported: "Partially supported",
  transferable: "Transferable experience",
  unknown: "Not enough evidence",
  apparent_gap: "Possible gap",
} as const;

const descriptionCache = new Map<string, string>();
const MAX_DESCRIPTION_CACHE_ENTRIES = 20;

function isAbortError(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
}

function cacheDescription(jobId: string, description: string) {
  descriptionCache.delete(jobId);
  descriptionCache.set(jobId, description);
  while (descriptionCache.size > MAX_DESCRIPTION_CACHE_ENTRIES) {
    const oldest = descriptionCache.keys().next().value;
    if (oldest === undefined) break;
    descriptionCache.delete(oldest);
  }
}

export function JobDetailPanel({
  job,
  companyBlocked,
  companyBusy,
  pendingAction,
  queueLoading,
  onClose,
  onChangeCompany,
  onDisposition,
  onScreened,
}: Props) {
  const assistant = useAssistant();
  const heading = useRef<HTMLHeadingElement>(null);
  const [recommendation, setRecommendation] = useState<ResumeRecommendation | null>(null);
  const [recommendationError, setRecommendationError] = useState("");
  const [jobScreen, setJobScreen] = useState<JobScreenResult | null>(null);
  const [screeningJobId, setScreeningJobId] = useState<string | null>(null);
  const [screeningMessage, setScreeningMessage] = useState("");
  const [screenError, setScreenError] = useState("");
  const [feedback, setFeedback] = useState<JobFeedback | null>(null);
  const [feedbackError, setFeedbackError] = useState("");
  const [description, setDescription] = useState<string | null>(job.description ?? descriptionCache.get(job.id) ?? null);
  const [descriptionError, setDescriptionError] = useState("");
  const currentJobId = useRef(job.id);
  const screenPollToken = useRef(0);
  currentJobId.current = job.id;
  const screening = screeningJobId === job.id;

  useEffect(() => {
    if (window.matchMedia?.("(max-width: 900px)").matches) heading.current?.focus();
  }, [job.id]);

  useEffect(() => {
    let active = true;
    const pollToken = ++screenPollToken.current;
    setRecommendation(null);
    setRecommendationError("");
    setJobScreen(null);
    setScreeningJobId(null);
    setScreeningMessage("");
    setScreenError("");
    setFeedback(null);
    setFeedbackError("");
    setDescription(job.description ?? descriptionCache.get(job.id) ?? null);
    setDescriptionError("");
    const controller = new AbortController();
    const descriptionRequest = job.description !== undefined || descriptionCache.has(job.id)
      ? Promise.resolve(null)
      : getJob(job.id, controller.signal);
    void Promise.allSettled([getResumeRecommendation(job.id), getJobScreenStatus(job.id), getJobFeedback(job.id), descriptionRequest]).then(([resumeResult, screenResult, feedbackResult, descriptionResult]) => {
      if (!active) return;
      if (resumeResult.status === "fulfilled") setRecommendation(resumeResult.value);
      else setRecommendationError(resumeResult.reason instanceof Error ? resumeResult.reason.message : "Could not load the resume recommendation.");
      if (screenResult.status === "fulfilled") {
        if (screenResult.value.status === "complete") setJobScreen(screenResult.value);
        else if (screenResult.value.status === "queued" || screenResult.value.status === "running") {
          setScreeningJobId(job.id);
          setScreeningMessage(screenResult.value.status === "running" ? "Analyzing in background" : "Analysis queued");
          void pollJobScreen(job.id, pollToken);
        } else if (screenResult.value.status === "failed") {
          setScreenError(screenResult.value.message ?? "The background analysis could not finish.");
        }
      } else setScreenError(screenResult.reason instanceof Error ? screenResult.reason.message : "Could not load this job screen.");
      if (feedbackResult.status === "fulfilled") setFeedback(feedbackResult.value);
      else setFeedbackError(feedbackResult.reason instanceof Error ? feedbackResult.reason.message : "Could not load your preference for this job.");
      if (descriptionResult.status === "fulfilled" && descriptionResult.value) {
        const loadedDescription = descriptionResult.value.description ?? "";
        cacheDescription(job.id, loadedDescription);
        setDescription(loadedDescription);
      } else if (descriptionResult.status === "rejected" && !isAbortError(descriptionResult.reason)) {
        setDescriptionError(descriptionResult.reason instanceof Error ? descriptionResult.reason.message : "Could not load the job description.");
      }
    });
    return () => { active = false; screenPollToken.current += 1; controller.abort(); };
  }, [job.id]);

  async function runJobScreen() {
    if (screening) return;
    const requestedJobId = job.id;
    const pollToken = ++screenPollToken.current;
    setScreeningJobId(requestedJobId);
    setScreeningMessage("Analysis queued");
    setScreenError("");
    try {
      const started = await screenJob(requestedJobId);
      if (currentJobId.current !== requestedJobId) return;
      if (started.status === "complete") {
        setJobScreen(started);
        onScreened(started);
        setFeedback(await getJobFeedback(requestedJobId));
        setScreeningJobId(null);
        setScreeningMessage("");
        return;
      }
      if (started.status === "failed") {
        setScreenError(started.message ?? "The background analysis could not finish.");
        setScreeningJobId(null);
        setScreeningMessage("");
        return;
      }
      setScreeningMessage(started.status === "running" ? "Analyzing in background" : "Analysis queued");
      void pollJobScreen(requestedJobId, pollToken);
    } catch (reason) {
      if (currentJobId.current === requestedJobId) setScreenError(reason instanceof Error ? reason.message : "Could not screen this job.");
      setScreeningJobId((current) => current === requestedJobId ? null : current);
      setScreeningMessage("");
    }
  }

  async function pollJobScreen(requestedJobId: string, pollToken: number) {
    for (let attempt = 0; attempt < 30; attempt += 1) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (currentJobId.current !== requestedJobId || screenPollToken.current !== pollToken) return;
      try {
        const state = await getJobScreenStatus(requestedJobId);
        if (currentJobId.current !== requestedJobId || screenPollToken.current !== pollToken) return;
        if (state.status === "complete") {
          setJobScreen(state);
          onScreened(state);
          setFeedback(await getJobFeedback(requestedJobId));
          setScreeningJobId(null);
          setScreeningMessage("");
          return;
        }
        if (state.status === "failed") {
          setScreenError(state.message ?? "The background analysis could not finish.");
          setScreeningJobId(null);
          setScreeningMessage("");
          return;
        }
        setScreeningMessage(state.status === "running" ? "Analyzing in background" : "Analysis queued");
      } catch (reason) {
        setScreenError(reason instanceof Error ? reason.message : "Could not check the background analysis.");
        setScreeningJobId(null);
        setScreeningMessage("");
        return;
      }
    }
    if (currentJobId.current === requestedJobId && screenPollToken.current === pollToken) {
      setScreenError("Analysis is still running in the background. You can close this job and return later.");
      setScreeningJobId(null);
      setScreeningMessage("");
    }
  }

  async function markInterested() {
    setFeedbackError("");
    const result = await onDisposition("interested");
    if (result) setFeedback(result);
  }

  const postedSalary = formatPayRange(job);
  const contextName = `${job.title} at ${job.company}`;
  const recommendationLabel = feedback?.personalization.hot_label === "Hot job"
    ? "Hot recommendation"
    : feedback?.personalization.hot_label ?? "Learning your preferences";
  const checkedCriteria = jobScreen?.result.evidence_strategy === "criterion-driven"
    ? jobScreen.result.criterion_evidence?.filter((item) => item.status !== "not-resume-evaluable").length ?? 0
    : 0;
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
        {recommendation?.recommended_resume && !jobScreen?.result.resume_match && <div className="resume-recommendation">
          <span>Recommended resume</span>
          <strong>{recommendation.recommended_resume.name}</strong>
          {recommendation.match && <em>{recommendation.match.label}</em>}
        </div>}
        {recommendation?.status === "unavailable" && recommendation.message && !jobScreen?.result.resume_match && <p className="recommendation-empty">{recommendation.message}</p>}
        {recommendationError && <p className="recommendation-error" role="status">{recommendationError}</p>}
        <section className="job-screen-card" aria-label="Job screen">
          {screening && !jobScreen ? <>
            <div>
              <strong>{screeningMessage || "Analysis queued"}</strong>
              <p>You can close this job and keep reviewing. The result will be saved here.</p>
            </div>
            <div className="job-screen-actions"><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : jobScreen ? <>
            <div className="job-screen-heading">
              <div><span>{jobScreen.result.screening_label}</span><strong>{jobScreen.result.fit_label}</strong></div>
              <em>{jobScreen.result.screening_label === "Quick screen" ? `${jobScreen.result.confidence} confidence · ` : ""}{jobScreen.result.eligibility_label}</em>
            </div>
            <details className="job-screen-rationale">
              <summary>Why this fit</summary>
              <p>{jobScreen.result.reasoning_summary}</p>
            </details>
            {jobScreen.result.resume_match && <div className="job-resume-match">
              <div className="job-resume-heading">
                <span>Best resume</span>
                <a href={`/api/resume-preview?resume_id=${encodeURIComponent(jobScreen.result.resume_match.resume_id)}`} target="_blank" rel="noreferrer">{jobScreen.result.resume_match.name}</a>
                {jobScreen.result.resume_match.label !== "Unknown match" && <strong>{jobScreen.result.resume_match.label}</strong>}
              </div>
              {(jobScreen.result.resume_match.strongest_overlap.length > 0 || jobScreen.result.resume_match.primary_gap) && <dl className="job-resume-signals">
                {jobScreen.result.resume_match.strongest_overlap.length > 0 && <div><dt>Strongest overlap</dt><dd>{jobScreen.result.resume_match.strongest_overlap.join(" · ")}</dd></div>}
                {jobScreen.result.resume_match.primary_gap && <div><dt>Primary gap</dt><dd>{jobScreen.result.resume_match.primary_gap}</dd></div>}
              </dl>}
            </div>}
            {jobScreen.result.preference_fit.label !== "No job preferences saved" && <div className="job-preference-fit">
              <span>What you want</span><strong>{jobScreen.result.preference_fit.label}</strong>
              {[...jobScreen.result.preference_fit.matches, ...jobScreen.result.preference_fit.conflicts].map((item) => <p key={`${item.direction}-${item.preference}`}><b>{item.outcome === "match" ? "Matches" : "Concern"}:</b> {item.explanation}</p>)}
              {jobScreen.result.preference_fit.unknown_count > 0 && <small>{jobScreen.result.preference_fit.unknown_count} saved {jobScreen.result.preference_fit.unknown_count === 1 ? "preference was" : "preferences were"} not clear from this posting.</small>}
            </div>}
            {(jobScreen.result.evidence_used.length > 0 || checkedCriteria > 0) && <dl className="job-screen-coverage">
              {jobScreen.result.evidence_used.length > 0 && <div><dt>{jobScreen.result.evidence_used.length}</dt><dd>Verified {jobScreen.result.evidence_used.length === 1 ? "fact" : "facts"}</dd></div>}
              {checkedCriteria > 0 && <div><dt>{checkedCriteria}</dt><dd>{checkedCriteria === 1 ? "Criterion" : "Criteria"} checked</dd></div>}
            </dl>}
            {jobScreen.result.posting_coverage === "partial" && <p className="job-screen-warning">This posting exceeded the quick-screen limit, so the result uses partial posting context.</p>}
            <div className="job-screen-disclosures">
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
            </div>
            <div className="job-screen-actions"><button className="text-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening…" : "Refresh screen"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : job.quick_screen?.status === "complete" ? <>
            <div>
              <strong>Screened in background</strong>
              <p>The background quick screen completed with a {job.quick_screen.label === "Unknown" ? "unclear" : job.quick_screen.label.toLowerCase()} result. Run it again to view a current evidence check.</p>
            </div>
            <div className="job-screen-actions"><button className="secondary-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening job…" : "Run screen again"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : job.quick_screen?.status === "failed" ? <>
            <div>
              <strong>Background screen failed</strong>
              <p>The automatic screen could not finish. Try again here for a current result.</p>
            </div>
            <div className="job-screen-actions"><button className="secondary-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening job…" : "Try screening again"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : job.quick_screen?.status === "skipped" ? <>
            <div>
              <strong>Not screened automatically</strong>
              <p>This job was skipped by the background screen. You can run a screen now.</p>
            </div>
            <div className="job-screen-actions"><button className="secondary-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening job…" : "Screen job"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : <>
            <div>
              <strong>Not screened yet</strong>
              <p>Run a quick check for eligibility and résumé fit. Company research is separate.</p>
            </div>
            <div className="job-screen-actions"><button className="secondary-button" onClick={() => void runJobScreen()} disabled={screening}>{screening ? "Screening job…" : "Screen job"}</button><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </>}
          {screenError && <p className="recommendation-error" role="alert">{screenError}</p>}
        </section>
        <section className="job-preference-card" aria-label="Your job preference">
          <div className="job-preference-heading">
            <div>
              <strong>{recommendationLabel}</strong>
              {jobScreen && feedback && <span>{feedback.personalization.interest_label} interest alignment{feedback.personalization.company_label !== "Neutral" ? ` · ${feedback.personalization.company_label} company preference` : ""}</span>}
              {!jobScreen && feedback && <span>Based on your saved requirements and interests.</span>}
              {!jobScreen && !feedback && <span>Loading recommendation details…</span>}
            </div>
            <button className="secondary-button interested-button" aria-pressed={feedback?.latest?.action === "interested"} disabled={pendingAction !== null} onClick={() => void markInterested()}>
              {pendingAction === "interested" ? "Saving…" : feedback?.latest?.action === "interested" ? "Interested ✓" : "Interested"}
            </button>
          </div>
          {feedbackError && <p className="recommendation-error" role="alert">{feedbackError}</p>}
        </section>
        <div className="job-actions" aria-label="Update job status">
          {job.url && <a className="secondary-button original-link" href={job.url} target="_blank" rel="noreferrer" onClick={() => { void recordJobPostingOpened(job.id).catch((reason: unknown) => console.warn("Could not record posting open", reason)); }}>Open posting <ArrowIcon /></a>}
          <button className="primary-button apply-button" onClick={() => void onDisposition("applied")} disabled={pendingAction !== null}>
            {pendingAction === "applied" ? "Moving to Applications…" : "Mark as applied"}
          </button>
          <button className="secondary-button reject-button" onClick={() => void onDisposition("not_interested")} disabled={pendingAction !== null}>
            {pendingAction === "not_interested" ? "Removing…" : "Not interested"}
          </button>
        </div>
      </div>
      <div className="job-description">
        {descriptionError
          ? <p>{descriptionError}</p>
          : description === null
            ? <p>Loading job description…</p>
            : description
              ? description.split(/\n+/).map((paragraph, index) => paragraph.trim() && <p key={index}>{paragraph}</p>)
              : <p>No description was included with this listing.</p>}
      </div>
    </aside>
  );
}
