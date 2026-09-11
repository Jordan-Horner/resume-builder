import { useEffect, useRef, useState } from "react";
import { getJob, getJobFeedback, getJobScreenStatus, getResumeRecommendation, recordJobPostingOpened, screenJob } from "../api";
import { ArrowIcon, IconButton } from "../components";
import { JobSalary } from "../components/JobSalary";
import { useAssistant } from "../assistant/AssistantProvider";
import type { Job, JobFeedback, JobFeedbackAction, JobHideReason, JobScreenResult, ResumeRecommendation } from "../types";
import { formatPayRange, formatWorkModes } from "./jobFormatters";

interface Props {
  job: Job;
  companyBlocked: boolean;
  companyBusy: boolean;
  pendingAction: JobFeedbackAction | "applied" | "hide" | null;
  queueLoading: boolean;
  onClose: () => void;
  onChangeCompany: (company: string, blocked: boolean) => Promise<void>;
  onDisposition: (disposition: JobFeedbackAction | "applied", resumeId?: string) => Promise<JobFeedback | null>;
  onHide: (reason: JobHideReason) => Promise<void>;
  onScreened: (screen: JobScreenResult) => void;
}

const criterionOutcomeLabels = {
  supported: "Supported",
  partially_supported: "Partially supported",
  transferable: "Transferable experience",
  unknown: "Not enough evidence",
  apparent_gap: "Possible gap",
} as const;

const MAX_JOB_DETAIL_CACHE_ENTRIES = 20;

function jobDetailCache<T>() {
  const map = new Map<string, T>();
  return {
    get: (jobId: string) => map.get(jobId),
    has: (jobId: string) => map.has(jobId),
    set(jobId: string, value: T) {
      map.delete(jobId);
      map.set(jobId, value);
      while (map.size > MAX_JOB_DETAIL_CACHE_ENTRIES) {
        const oldest = map.keys().next().value;
        if (oldest === undefined) break;
        map.delete(oldest);
      }
    },
    clear: () => map.clear(),
  };
}

// Reopening a previously viewed job (close, browse, click back) should not
// re-show a blank/"Not screened yet" flash for data that hasn't changed.
// The description and a completed screen are immutable once fetched, so a
// cache hit skips the network call entirely; the recommendation and feedback
// can change between visits, so a cache hit still renders instantly but
// revalidates in the background.
const descriptionCache = jobDetailCache<string>();
const recommendationCache = jobDetailCache<ResumeRecommendation>();
const feedbackCache = jobDetailCache<JobFeedback>();
const screenCache = jobDetailCache<JobScreenResult>();

/** Test-only: forget every cached job detail so each test starts from a clean slate. */
export function __resetJobDetailCaches(): void {
  descriptionCache.clear();
  recommendationCache.clear();
  feedbackCache.clear();
  screenCache.clear();
}

function isAbortError(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
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
  onHide,
  onScreened,
}: Props) {
  const assistant = useAssistant();
  const heading = useRef<HTMLHeadingElement>(null);
  const hideReasons = useRef<HTMLElement>(null);
  const [recommendation, setRecommendation] = useState<ResumeRecommendation | null>(null);
  const [recommendationError, setRecommendationError] = useState("");
  const [selectedResumeId, setSelectedResumeId] = useState("");
  const [jobScreen, setJobScreen] = useState<JobScreenResult | null>(null);
  const [screeningJobId, setScreeningJobId] = useState<string | null>(null);
  const [screeningMessage, setScreeningMessage] = useState("");
  const [screenError, setScreenError] = useState("");
  const [feedback, setFeedback] = useState<JobFeedback | null>(null);
  const [feedbackError, setFeedbackError] = useState("");
  const [showHideReasons, setShowHideReasons] = useState(false);
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
    const cachedScreen = screenCache.get(job.id) ?? null;
    const cachedRecommendation = recommendationCache.get(job.id) ?? null;
    const cachedFeedback = feedbackCache.get(job.id) ?? null;
    setRecommendation(cachedRecommendation);
    setRecommendationError("");
    setSelectedResumeId(cachedRecommendation?.recommended_resume?.id
      ?? (cachedRecommendation?.available_resumes.length === 1 ? cachedRecommendation.available_resumes[0].id : ""));
    setJobScreen(cachedScreen);
    setScreeningJobId(null);
    setScreeningMessage("");
    setScreenError("");
    setFeedback(cachedFeedback);
    setFeedbackError("");
    setShowHideReasons(false);
    setDescription(job.description ?? descriptionCache.get(job.id) ?? null);
    setDescriptionError("");
    const controller = new AbortController();
    const descriptionRequest = job.description !== undefined || descriptionCache.has(job.id)
      ? Promise.resolve(null)
      : getJob(job.id, controller.signal);
    // A completed screen never changes on its own, so a cache hit skips the
    // status check entirely instead of re-polling for a result already held.
    if (!cachedScreen) void getJobScreenStatus(job.id, controller.signal).then((state) => {
      if (!active) return;
      if (state.status === "complete") { screenCache.set(job.id, state); setJobScreen(state); }
      else if (state.status === "queued" || state.status === "running") {
        setScreeningJobId(job.id);
        setScreeningMessage(state.status === "running" ? "Analyzing in background" : "Analysis queued");
        void pollJobScreen(job.id, pollToken);
      } else if (state.status === "failed") {
        setScreenError(state.message ?? "The background analysis could not finish.");
      }
    }).catch((reason: unknown) => {
      if (!active || isAbortError(reason)) return;
      setScreenError(reason instanceof Error ? reason.message : "Could not load this job screen.");
    });
    void getResumeRecommendation(job.id, controller.signal).then((value) => {
      if (active) {
        recommendationCache.set(job.id, value);
        setRecommendation(value);
        setSelectedResumeId(value.recommended_resume?.id ?? (value.available_resumes.length === 1 ? value.available_resumes[0].id : ""));
      }
    }).catch((reason: unknown) => {
      if (active && !isAbortError(reason) && !cachedRecommendation) {
        setRecommendationError(reason instanceof Error ? reason.message : "Could not load the resume recommendation.");
      }
    });
    void getJobFeedback(job.id, controller.signal).then((value) => {
      if (active) { feedbackCache.set(job.id, value); setFeedback(value); }
    }).catch((reason: unknown) => {
      if (active && !isAbortError(reason) && !cachedFeedback) {
        setFeedbackError(reason instanceof Error ? reason.message : "Could not load your preference for this job.");
      }
    });
    void descriptionRequest.then((value) => {
      if (active && value) {
        const loadedDescription = value.description ?? "";
        descriptionCache.set(job.id, loadedDescription);
        setDescription(loadedDescription);
      }
    }).catch((reason: unknown) => {
      if (active && !isAbortError(reason)) {
        setDescriptionError(reason instanceof Error ? reason.message : "Could not load the job description.");
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
        screenCache.set(requestedJobId, started);
        setJobScreen(started);
        onScreened(started);
        setScreeningJobId(null);
        setScreeningMessage("");
        void refreshFeedback(requestedJobId);
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
    while (currentJobId.current === requestedJobId && screenPollToken.current === pollToken) {
      await new Promise((resolve) => window.setTimeout(resolve, 1000));
      if (currentJobId.current !== requestedJobId || screenPollToken.current !== pollToken) return;
      try {
        const state = await getJobScreenStatus(requestedJobId);
        if (currentJobId.current !== requestedJobId || screenPollToken.current !== pollToken) return;
        if (state.status === "complete") {
          screenCache.set(requestedJobId, state);
          setJobScreen(state);
          onScreened(state);
          setScreeningJobId(null);
          setScreeningMessage("");
          void refreshFeedback(requestedJobId);
          return;
        }
        if (state.status === "failed") {
          setScreenError(state.message ?? "The background analysis could not finish.");
          setScreeningJobId(null);
          setScreeningMessage("");
          return;
        }
        if (state.status === "idle") {
          setScreenError("The background analysis stopped before it finished. You can try again.");
          setScreeningJobId(null);
          setScreeningMessage("");
          return;
        }
        setScreenError("");
        setScreeningMessage(state.status === "running" ? "Analyzing in background" : "Analysis queued");
      } catch (reason) {
        setScreenError(reason instanceof Error ? `${reason.message} Retrying…` : "Could not check the background analysis. Retrying…");
        setScreeningMessage("Analysis is still running");
      }
    }
  }

  async function refreshFeedback(requestedJobId: string) {
    try {
      const value = await getJobFeedback(requestedJobId);
      feedbackCache.set(requestedJobId, value);
      if (currentJobId.current === requestedJobId) setFeedback(value);
    } catch (reason) {
      if (currentJobId.current === requestedJobId) {
        setFeedbackError(reason instanceof Error ? reason.message : "Could not refresh your preference for this job.");
      }
    }
  }

  async function markInterested() {
    setFeedbackError("");
    const result = await onDisposition("interested");
    if (result) { feedbackCache.set(job.id, result); setFeedback(result); }
  }

  function toggleHideReasons() {
    const willShow = !showHideReasons;
    setShowHideReasons(willShow);
    if (willShow) {
      window.requestAnimationFrame(() => hideReasons.current?.scrollIntoView?.({ block: "nearest" }));
    }
  }

  const postedSalary = formatPayRange(job);
  const contextName = `${job.title} at ${job.company}`;
  const personalization = feedback?.personalization ?? job.personalization;
  const recommendationLabel = personalization?.hot_label === "Hot job"
    ? "Hot recommendation"
    : personalization?.hot_label ?? "Learning your preferences";
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
          {job.company_recognition?.top_workplace && <span className="recognition-badge top-workplace">Top workplace</span>}
          {job.company_recognition?.major_employer && <span className="recognition-badge major-employer">Major employer</span>}
        </div>
        {!jobScreen && recommendation?.recommended_resume && <div className="resume-recommendation">
          <span>Recommended resume</span>
          <strong>{recommendation.recommended_resume.name}</strong>
          {recommendation.match && <em>{recommendation.match.label}</em>}
        </div>}
        {!jobScreen && recommendation?.status === "unavailable" && recommendation.message && <p className="recommendation-empty">{recommendation.message}</p>}
        {recommendation?.status === "unavailable" && recommendation.available_resumes.length > 0 && <label className="resume-choice">
          <span>Resume used</span>
          <select value={selectedResumeId} onChange={(event) => setSelectedResumeId(event.target.value)}>
            <option value="">Choose a resume</option>
            {recommendation.available_resumes.map((resume) => <option key={resume.id} value={resume.id}>{resume.name}</option>)}
          </select>
        </label>}
        {recommendationError && <p className="recommendation-error" role="status">{recommendationError}</p>}
        <section className="job-screen-card" aria-label="Job screen">
          {screening && !jobScreen ? <>
            <div>
              <strong>{screeningMessage || "Analysis queued"}</strong>
              <p>You can close this job and keep reviewing. The result will be saved here.</p>
            </div>
            <div className="job-screen-actions"><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : jobScreen ? <>
            <div className="job-fit-comparison">
              <div className="job-fit-result">
                <span className="job-fit-label">Career fit</span>
                <strong className="job-fit-rating">{jobScreen.result.fit_label}</strong>
                <small>{jobScreen.result.screening_label}{jobScreen.result.screening_label === "Quick screen" ? ` · ${jobScreen.result.confidence} confidence` : ""} · {jobScreen.result.eligibility_label}</small>
              </div>
              <div className="job-fit-result job-resume-match">
                <span className="job-fit-label">Resume match</span>
                {jobScreen.result.resume_match ? <>
                  <strong className="job-fit-rating job-fit-rating-accent">{jobScreen.result.resume_match.label}</strong>
                  <a href={`/api/resume-preview?resume_id=${encodeURIComponent(jobScreen.result.resume_match.resume_id)}`} target="_blank" rel="noreferrer">{jobScreen.result.resume_match.name}</a>
                  {(jobScreen.result.resume_match.strongest_overlap.length > 0 || jobScreen.result.resume_match.primary_gap) && <dl className="job-resume-signals">
                    {jobScreen.result.resume_match.strongest_overlap.length > 0 && <div><dt>Strongest overlap</dt><dd>{jobScreen.result.resume_match.strongest_overlap.join(" · ")}</dd></div>}
                    {jobScreen.result.resume_match.primary_gap && <div><dt>Primary gap</dt><dd>{jobScreen.result.resume_match.primary_gap}</dd></div>}
                  </dl>}
                </> : <>
                  <strong className="job-fit-rating job-fit-rating-muted">{jobScreen.result.resume_guidance?.label ?? "Needs tailoring"}</strong>
                  <small>{jobScreen.result.resume_guidance?.detail ?? `${jobScreen.result.evidence_used.length} verified vault ${jobScreen.result.evidence_used.length === 1 ? "fact supports" : "facts support"} this job, but the screen could not choose a single best current resume. Compare or tailor your resumes before applying.`}</small>
                </>}
              </div>
            </div>
            <details className="job-screen-rationale">
              <summary>Why this fit</summary>
              <p>{jobScreen.result.reasoning_summary}</p>
            </details>
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
            <div className="job-screen-actions"><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
          </> : job.quick_screen?.status === "complete" ? <>
            <div>
              <strong>{job.quick_screen.label}</strong>
              <p>Quick screen complete.</p>
            </div>
            <div className="job-screen-actions"><button className="text-button" onClick={() => assistant.discussJob(job.id, contextName)}>Discuss job</button></div>
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
              {jobScreen && personalization?.interest_label && <span>{personalization.interest_label} interest alignment{personalization.company_label && personalization.company_label !== "Neutral" ? ` · ${personalization.company_label} company preference` : ""}</span>}
              {!jobScreen && personalization && <span>Based on your saved requirements and interests.</span>}
              {!personalization && <span>Learning from the jobs you pursue.</span>}
            </div>
            <button className="secondary-button interested-button" aria-pressed={feedback?.latest?.action === "interested"} disabled={pendingAction !== null} onClick={() => void markInterested()}>
              {pendingAction === "interested" ? "Saving…" : feedback?.latest?.action === "interested" ? "Interested ✓" : "Interested"}
            </button>
          </div>
          {feedbackError && <p className="recommendation-error" role="alert">{feedbackError}</p>}
        </section>
        <div className="job-actions" aria-label="Update job status">
          {job.url && <a className="secondary-button original-link" href={job.url} target="_blank" rel="noreferrer" onClick={() => { void recordJobPostingOpened(job.id).catch((reason: unknown) => console.warn("Could not record posting open", reason)); }}>Open posting <ArrowIcon /></a>}
          <button className="primary-button apply-button" onClick={() => void onDisposition("applied", selectedResumeId || undefined)} disabled={pendingAction !== null || (recommendation?.status === "unavailable" && recommendation.available_resumes.length > 0 && !selectedResumeId)}>
            {pendingAction === "applied" ? "Moving to Applications…" : recommendation?.status === "unavailable" && recommendation.available_resumes.length > 0 && !selectedResumeId ? "Choose resume first" : "Mark as applied"}
          </button>
          <button className="secondary-button hide-posting-button" aria-expanded={showHideReasons} aria-controls="hide-posting-reasons" onClick={toggleHideReasons} disabled={pendingAction !== null}>
            {pendingAction === "hide" ? "Hiding…" : "Hide posting"}
          </button>
        </div>
        {showHideReasons && <section ref={hideReasons} id="hide-posting-reasons" className="hide-posting-reasons" aria-labelledby="hide-posting-heading">
          <div>
            <strong id="hide-posting-heading">Why hide this posting?</strong>
            <p>Only “Not interested” changes future recommendations.</p>
          </div>
          <div className="hide-posting-options">
            <button className="secondary-button" onClick={() => void onHide("closed")} disabled={pendingAction !== null}>Posting is closed</button>
            <button className="secondary-button" onClick={() => void onHide("duplicate")} disabled={pendingAction !== null}>Duplicate posting</button>
            <button className="secondary-button preference-feedback-button" onClick={() => void onHide("not_relevant")} disabled={pendingAction !== null}>Not interested</button>
          </div>
        </section>}
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
