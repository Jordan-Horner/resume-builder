import { type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";
import {
  activateJobSearch, getBlockedCompanies, getJobFilterDefaults, getJobs, getJobSources,
  getScrapeSchedule, getSearchPreferences, hideJobPosting, markJobApplied, saveJobFeedback, setCompanyBlocked,
  startJobScan,
} from "../api";
import { EmptyState, ErrorMessage, LoadingRows, SearchField } from "../components";
import { JobViewFilters } from "../JobViewFilters";
import { JobDetailPanel } from "../jobs/JobDetailPanel";
import { formatCompactCurrency, formatWorkModes } from "../jobs/jobFormatters";
import { JobRow } from "../jobs/JobRow";
import { useAssistant } from "../assistant/AssistantProvider";
import type { Job, JobFeedback, JobFeedbackAction, JobFilters, JobHideReason, JobScreenResult, SearchPreferences, ViewFilters } from "../types";
import { EMPTY_FILTERS, persistView, restoreView } from "../viewPreferences";

const DATE_FILTERS = [
  { label: "Any date", value: 0 }, { label: "Last 24 hours", value: 1 },
  { label: "Last 3 days", value: 3 }, { label: "Last 7 days", value: 7 },
  { label: "Last 2 weeks", value: 14 }, { label: "Last 30 days", value: 30 },
] as const;
const companyKey = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
type JobQueue = "all" | "recommended" | "interested";
type JobQueuePayload = { jobs: Job[]; count: number; reviewable_count: number };
const MAX_QUEUE_CACHE_ENTRIES = 6;
const NOTICE_DURATION_MS = 8000;

function textFiltersChanged(previous: JobFilters, next: JobFilters) {
  return previous.search !== next.search
    || (previous.view?.locations.join("\n") ?? "") !== (next.view?.locations.join("\n") ?? "");
}

function useDebouncedFilters(filters: JobFilters, delay = 250) {
  const [debounced, setDebounced] = useState(filters);
  useEffect(() => {
    if (!textFiltersChanged(debounced, filters)) {
      setDebounced(filters);
      return;
    }
    const timer = window.setTimeout(() => setDebounced(filters), delay);
    return () => window.clearTimeout(timer);
  }, [debounced, delay, filters]);
  return debounced;
}

function isAbortError(reason: unknown) {
  return reason instanceof DOMException && reason.name === "AbortError";
}

export function JobsPage() {
  const assistant = useAssistant();
  const [filters, setFilters] = useState<JobFilters>(EMPTY_FILTERS);
  const [defaults, setDefaults] = useState<ViewFilters | null>(null);
  const [preferencesUpdated, setPreferencesUpdated] = useState(false);
  const deferredFilters = useDebouncedFilters(filters);
  const { search, dateDays } = filters;
  const deferredSearch = deferredFilters.search;
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [reviewableTotal, setReviewableTotal] = useState(0);
  const [searchPreferences, setSearchPreferences] = useState<SearchPreferences | null>(null);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [queueRefreshing, setQueueRefreshing] = useState(false);
  const [error, setError] = useState("");
  const [queueError, setQueueError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [queueRevision, setQueueRevision] = useState(0);
  const [pendingAction, setPendingAction] = useState<JobFeedbackAction | "applied" | "hide" | null>(null);
  const [notice, setNotice] = useState("");
  const [queueView, setQueueView] = useState<JobQueue>("recommended");
  const [recommendationStage, setRecommendationStage] = useState<"idle" | "searching" | "screening">("idle");
  const [blockedCompanies, setBlockedCompanies] = useState<string[]>([]);
  const [companyBusy, setCompanyBusy] = useState(false);
  const selectedOrigin = useRef<HTMLButtonElement | null>(null);
  const results = useRef<HTMLElement | null>(null);
  const focusQueueAfterRefresh = useRef(false);
  const silentQueueRefresh = useRef(false);
  const queueCache = useRef(new Map<string, JobQueuePayload>());
  const queueRequests = useRef(new Map<string, Promise<JobQueuePayload>>());
  const queueControllers = useRef(new Map<string, AbortController>());

  function queueKey(queue: JobQueue) {
    return JSON.stringify([reloadKey, queueRevision, queue, deferredFilters]);
  }

  function loadQueue(queue: JobQueue) {
    const key = queueKey(queue);
    const cached = queueCache.current.get(key);
    if (cached) return Promise.resolve(cached);
    const pending = queueRequests.current.get(key);
    if (pending) return pending;
    const controller = new AbortController();
    const request = getJobs(deferredFilters, queue, controller.signal).then((payload) => {
      queueCache.current.delete(key);
      queueCache.current.set(key, payload);
      while (queueCache.current.size > MAX_QUEUE_CACHE_ENTRIES) {
        const oldest = queueCache.current.keys().next().value;
        if (oldest === undefined) break;
        queueCache.current.delete(oldest);
      }
      return payload;
    }).finally(() => {
      queueRequests.current.delete(key);
      queueControllers.current.delete(key);
    });
    queueRequests.current.set(key, request);
    queueControllers.current.set(key, controller);
    return request;
  }

  function showQueue(payload: JobQueuePayload) {
    setJobs(payload.jobs);
    setTotal(payload.count);
    setReviewableTotal(payload.reviewable_count);
  }

  function prefetchQueue(queue: JobQueue) {
    if (!defaults || deferredFilters !== filters || queue === queueView) return;
    void loadQueue(queue).catch((reason: unknown) => {
      if (!isAbortError(reason)) console.warn(`Could not prefetch the ${queue} job queue`, reason);
    });
  }

  useEffect(() => {
    for (const controller of queueControllers.current.values()) controller.abort();
    queueControllers.current.clear();
    queueRequests.current.clear();
    queueCache.current.clear();
  }, [deferredFilters, reloadKey, queueRevision]);

  function selectQueue(queue: JobQueue) {
    if (queue === queueView) return;
    setSelected(null);
    selectedOrigin.current = null;
    const cached = queueCache.current.get(queueKey(queue));
    setQueueError("");
    if (cached) {
      showQueue(cached);
      setLoading(false);
    } else {
      setLoading(true);
      if (deferredFilters === filters) {
        void loadQueue(queue).catch((reason: unknown) => {
          console.warn(`Could not start loading the ${queue} job queue`, reason);
        });
      }
    }
    setQueueView(queue);
  }

  function navigateQueueTabs(event: ReactKeyboardEvent<HTMLButtonElement>) {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    const tabs = Array.from(event.currentTarget.parentElement?.querySelectorAll<HTMLButtonElement>('[role="tab"]') ?? []);
    const currentIndex = tabs.indexOf(event.currentTarget);
    if (currentIndex < 0 || tabs.length === 0) return;
    event.preventDefault();
    const nextIndex = event.key === "Home"
      ? 0
      : event.key === "End"
        ? tabs.length - 1
        : (currentIndex + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[nextIndex]?.focus();
    tabs[nextIndex]?.click();
  }

  useEffect(() => {
    let active = true;
    getJobFilterDefaults().then((value) => {
      if (!active) return;
      setDefaults(value);
      try {
        const restored = restoreView(value);
        setFilters(restored.filters);
        setPreferencesUpdated(!!restored.updated);
      } catch (reason) {
        setFilters({ ...EMPTY_FILTERS, view: value });
        setError(reason instanceof Error ? reason.message : "Could not restore saved filters.");
      }
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load job preferences.");
    });
    return () => { active = false; };
  }, [reloadKey]);

  useEffect(() => {
    let active = true;
    getSearchPreferences().then((value) => { if (active) setSearchPreferences(value); }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load search preferences.");
    });
    return () => { active = false; };
  }, [reloadKey]);

  useEffect(() => {
    let active = true;
    getBlockedCompanies().then((value) => { if (active) setBlockedCompanies(value.companies); }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load blocked companies");
    });
    return () => { active = false; };
  }, [reloadKey]);

  useEffect(() => {
    if (!defaults) return;
    try { persistView(filters, defaults); }
    catch { setError("Your browser could not save these filters. They will last only while this page is open."); }
  }, [filters, defaults]);

  useEffect(() => {
    let active = true;
    if (!defaults || deferredFilters !== filters) return;
    const silent = silentQueueRefresh.current;
    silentQueueRefresh.current = false;
    const cached = queueCache.current.get(queueKey(queueView));
    setQueueError("");
    if (cached) {
      showQueue(cached);
      setLoading(false);
      return;
    }
    if (!silent) setLoading(true);
    loadQueue(queueView).then((payload) => {
      if (!active) return;
      showQueue(payload);
    }).catch((reason: unknown) => {
      if (!active) return;
      const message = reason instanceof Error ? reason.message : "Could not load jobs";
      if (silent) setError(`${message}. Your current queue is still shown.`);
      else setQueueError(message);
    }).finally(() => {
      if (!active) return;
      setLoading(false);
      if (silent) setQueueRefreshing(false);
    });
    return () => { active = false; };
  }, [deferredFilters, defaults, filters, reloadKey, queueRevision, queueView]);

  useEffect(() => {
    if (queueView !== "recommended") return;
    let active = true;
    let timer: number | undefined;
    let observedRunning = false;
    const poll = async () => {
      try {
        const schedule = await getScrapeSchedule();
        if (!active) return;
        setRecommendationStage(schedule.current_stage);
        if (schedule.current_stage !== "idle") {
          observedRunning = true;
          timer = window.setTimeout(() => void poll(), 3000);
        } else if (observedRunning) {
          setQueueRevision((value) => value + 1);
        }
      } catch (reason) {
        console.warn("Could not load recommendation progress", reason);
      }
    };
    void poll();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, [queueView, reloadKey]);

  useEffect(() => {
    if (loading || queueRefreshing || !focusQueueAfterRefresh.current) return;
    focusQueueAfterRefresh.current = false;
    (results.current?.querySelector<HTMLButtonElement>(".job-row") || results.current)?.focus();
  }, [jobs, loading, queueRefreshing]);

  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), NOTICE_DURATION_MS);
    return () => window.clearTimeout(timer);
  }, [notice]);

  async function changeCompany(company: string, blocked: boolean) {
    if (companyBusy || pendingAction) return;
    setCompanyBusy(true); setError("");
    try {
      const result = await setCompanyBlocked(company, blocked);
      setBlockedCompanies(result.companies);
      setNotice(`${company} ${blocked ? "blocked" : "unblocked"}.`);
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : `Could not ${blocked ? "block" : "unblock"} ${company}. Try again.`);
    } finally { setCompanyBusy(false); }
  }

  async function runManualScan() {
    if (scanning) return;
    setScanning(true); setError(""); setNotice("Searching enabled sources…");
    try {
      let state = await startJobScan();
      for (let attempt = 0; attempt < 120 && state.scan.status === "running"; attempt += 1) {
        await new Promise((resolve) => window.setTimeout(resolve, 1500));
        state = await getJobSources();
      }
      if (state.scan.status === "running") throw new Error("The search is still running. Check back in a moment.");
      if (state.scan.status === "failed") throw new Error(state.scan.message || "The search failed. Try again.");
      const found = state.scan.new_jobs || 0;
      setNotice(found ? `${found} new ${found === 1 ? "job" : "jobs"} found.` : "Search finished. No new jobs matched this time.");
      setReloadKey((key) => key + 1);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start a job search.");
    } finally { setScanning(false); }
  }

  async function finishSetup() {
    setError("");
    try {
      await activateJobSearch();
      setReloadKey((key) => key + 1);
      setNotice("Searches activated. You can find jobs now.");
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not activate your searches."); }
  }

  function openJob(job: Job, origin: HTMLButtonElement) {
    selectedOrigin.current = origin;
    setSelected(job);
  }

  function closeJob() {
    setSelected(null);
    window.requestAnimationFrame(() => selectedOrigin.current?.focus());
  }

  const selectedJobId = selected?.id;
  const selectedJobTitle = selected?.title;
  const selectedJobCompany = selected?.company;
  useEffect(() => {
    if (!selectedJobId || !selectedJobTitle || !selectedJobCompany) return;
    assistant.setWindowContext({
      kind: "job",
      id: selectedJobId,
      name: `${selectedJobTitle} at ${selectedJobCompany}`,
    });
  }, [assistant.setWindowContext, selectedJobCompany, selectedJobId, selectedJobTitle]);

  function updateQuickScreen(screen: JobScreenResult) {
    const resume = screen.result.resume_match;
    setJobs((current) => current.map((job) => job.id === screen.result.job_id ? {
      ...job,
      quick_screen: {
        status: "complete",
        label: resume?.label.replace(/ match$/, "") || screen.result.fit_label,
        resume_name: resume?.name || null,
        generated_at: null,
      },
    } : job));
  }

  function removeVisibleJob(jobId: string, removeFromInventory: boolean) {
    setJobs((current) => current.filter((job) => job.id !== jobId));
    setTotal((current) => Math.max(0, current - 1));
    if (removeFromInventory) setReviewableTotal((current) => Math.max(0, current - 1));
  }

  async function dispositionSelected(
    disposition: JobFeedbackAction | "applied",
  ): Promise<JobFeedback | null> {
    if (!selected || pendingAction || companyBusy) return null;
    const job = selected;
    setPendingAction(disposition); setError("");
    try {
      if (disposition === "interested") {
        const result = await saveJobFeedback(job.id, disposition, []);
        focusQueueAfterRefresh.current = true;
        if (queueView === "recommended") removeVisibleJob(job.id, false);
        silentQueueRefresh.current = true;
        setQueueRefreshing(true);
        setQueueRevision((value) => value + 1);
        setSelected(null);
        setNotice(`${job.title} saved to Interested jobs.`);
        return result;
      }
      if (disposition === "applied") await markJobApplied(job.id);
      else {
        const result = await saveJobFeedback(job.id, disposition, []);
        const followUp = result.dismissal_follow_up;
        if (followUp?.ask_why && followUp.prompt) {
          assistant.discussJob(job.id, `${job.title} at ${job.company}`, followUp.prompt);
        }
      }
      focusQueueAfterRefresh.current = true;
      removeVisibleJob(job.id, true);
      silentQueueRefresh.current = true;
      setQueueRefreshing(true);
      setQueueRevision((value) => value + 1);
      setSelected(null);
      setNotice(disposition === "applied" ? `${job.title} moved to Applications.` : `${job.title} removed from your job queue.`);
      return null;
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this job");
      return null;
    } finally { setPendingAction(null); }
  }

  async function hideSelected(reason: JobHideReason): Promise<void> {
    if (!selected || pendingAction || companyBusy) return;
    const job = selected;
    setPendingAction("hide"); setError("");
    try {
      const result = await hideJobPosting(job.id, reason);
      focusQueueAfterRefresh.current = true;
      removeVisibleJob(job.id, true);
      silentQueueRefresh.current = true;
      setQueueRefreshing(true);
      setQueueRevision((value) => value + 1);
      setSelected(null);
      setNotice(result.personalization_updated
        ? `${job.title} hidden. Recommendations will use this feedback.`
        : `${job.title} hidden. Similar roles will still be recommended.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not hide this posting");
    } finally { setPendingAction(null); }
  }

  const emptyState = searchPreferences?.status === "ready_to_activate"
    ? { title: "Finish setting up your search", message: "Activate your saved roles before searching.", actions: <button className="primary-button" onClick={() => void finishSetup()}>Finish setup</button> }
    : reviewableTotal === 0
      ? { title: "Find your first jobs", message: "Search your enabled sources using your saved roles and preferences.", actions: <><button className="primary-button" disabled={scanning} onClick={() => void runManualScan()}>{scanning ? "Finding jobs…" : "Find jobs now"}</button><a className="empty-state-link" href="/settings/search-preferences">Edit preferences</a></> }
      : queueView === "interested"
          ? { title: "No Interested jobs yet", message: "Jobs you mark Interested stay here until you apply or pass on them.", actions: <button className="primary-button" onClick={() => selectQueue("recommended")}>Review recommendations</button> }
          : queueView === "recommended"
            ? recommendationStage === "searching"
              ? { title: "Finding new jobs…", message: "Your scheduled search is running. Strong deterministic matches will appear here immediately.", actions: <button className="primary-button" onClick={() => selectQueue("all")}>Review all jobs</button> }
              : recommendationStage === "screening"
                ? { title: "Screening recommendations…", message: "The search finished. Career-fit screening is preparing your Recommended Jobs.", actions: <button className="primary-button" onClick={() => selectQueue("all")}>Review all jobs</button> }
                : { title: "No Recommended Jobs right now", message: "Recommendations use your saved roles, location, work setup, pay, and seniority. The strongest matches are screened automatically.", actions: <button className="primary-button" onClick={() => selectQueue("all")}>Review all jobs</button> }
        : { title: "No jobs match these filters", message: `${reviewableTotal} reviewable ${reviewableTotal === 1 ? "job is" : "jobs are"} hidden by your current filters.`, actions: <><button className="primary-button" onClick={() => defaults && setFilters({ ...EMPTY_FILTERS, view: defaults })}>Reset filters</button><button className="empty-state-link" onClick={() => setFilters(EMPTY_FILTERS)}>Clear all</button></> };

  const hasNoInventory = !loading && !queueError && reviewableTotal === 0;
  const savedRoles = searchPreferences?.titles || [];
  const savedModes = searchPreferences?.work_modes || [];
  const compensation = searchPreferences?.compensation;
  const roleSummary = savedRoles.length ? `${savedRoles.length} ${savedRoles.length === 1 ? "role" : "roles"}` : "No roles saved";
  const locationSummary = [searchPreferences?.country, savedModes.length ? formatWorkModes(savedModes) : null].filter(Boolean).join(" · ") || "Any location";
  const compensationSummary = compensation && !compensation.skipped && compensation.minimum
    ? `${formatCompactCurrency(compensation.minimum, compensation.currency || "USD")}+ minimum` : "Any compensation";
  const selectedCompanyBlocked = !!selected && blockedCompanies.some((company) => companyKey(company) === companyKey(selected.company));
  const noticeContent = notice && <>
    <span role="status">{notice}</span>
    <button className="notice-dismiss" type="button" aria-label="Dismiss notification" onClick={() => setNotice("")}>&times;</button>
  </>;

  return (
    <div className="page jobs-page">
      {!hasNoInventory && <section className="search-tools jobs-search-tools" aria-label="Search and filters">
        <SearchField label="Search jobs to review" disabled={!defaults} value={search} onChange={(event) => setFilters({ ...filters, search: event.target.value })} placeholder="Title, skill or company" />
        <SearchField label="State, city or region" wrapperClassName="location-search-field" icon={<svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>} disabled={!defaults} value={filters.view?.locations.join("; ") || ""} placeholder="State, city or region" title="Optional narrowing for on-site and hybrid jobs. Remote jobs remain in your country scope." onChange={(event) => filters.view && setFilters({ ...filters, view: { ...filters.view, locations: event.target.value ? [event.target.value] : [] } })} />
        <select value={dateDays} onChange={(event) => setFilters({ ...filters, dateDays: Number(event.target.value) as typeof dateDays })} aria-label="Date posted">
          {DATE_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
        </select>
        {!defaults && <span role="status">Loading preferences…</span>}
        {defaults && filters.view && <JobViewFilters value={filters.view} onChange={(view) => setFilters({ ...filters, view })} reset={() => setFilters({ ...EMPTY_FILTERS, view: defaults })} clear={() => setFilters(EMPTY_FILTERS)} />}
      </section>}
      {preferencesUpdated && defaults && <p className="action-notice">Your saved preferences changed. Custom filters were kept. <button className="text-button" onClick={() => { setFilters({ ...EMPTY_FILTERS, view: defaults }); setPreferencesUpdated(false); }}>Apply updated preferences</button></p>}

      <div className={selected ? "jobs-layout detail-open" : "jobs-layout"}>
        <section className="job-results" aria-live="polite" ref={results} tabIndex={-1}>
          {hasNoInventory && !error ? <div className="first-search" aria-labelledby="first-search-title">
            <p className="first-search-kicker">Your search is ready</p><h1 id="first-search-title">Build your job queue</h1>
            <p className="first-search-intro">Search every enabled source using the preferences you already chose.</p>
            <dl className="first-search-summary"><div><dt>Searching for</dt><dd>{roleSummary}</dd></div><div><dt>Where</dt><dd>{locationSummary}</dd></div><div><dt>Pay</dt><dd>{compensationSummary}</dd></div></dl>
            <div className="first-search-actions">
              {searchPreferences?.status === "ready_to_activate" ? <button className="primary-button" onClick={() => void finishSetup()}>Finish setup</button> : <button className="primary-button" disabled={scanning} onClick={() => void runManualScan()}>{scanning ? "Searching sources…" : "Find jobs now"}</button>}
              <a className="empty-state-link" href="/settings/search-preferences">Review search settings</a>
            </div>
            {notice && <div className="first-search-notice transient-notice">{noticeContent}</div>}
          </div> : <>
            <div className="queue-tabs" role="tablist" aria-label="Job queues">
              <button role="tab" tabIndex={queueView === "recommended" ? 0 : -1} aria-selected={queueView === "recommended"} onKeyDown={navigateQueueTabs} onMouseEnter={() => prefetchQueue("recommended")} onFocus={() => prefetchQueue("recommended")} onClick={() => selectQueue("recommended")}>Recommended Jobs</button>
              <button role="tab" tabIndex={queueView === "interested" ? 0 : -1} aria-selected={queueView === "interested"} onKeyDown={navigateQueueTabs} onMouseEnter={() => prefetchQueue("interested")} onFocus={() => prefetchQueue("interested")} onClick={() => selectQueue("interested")}>Interested jobs</button>
              <button role="tab" tabIndex={queueView === "all" ? 0 : -1} aria-selected={queueView === "all"} onKeyDown={navigateQueueTabs} onMouseEnter={() => prefetchQueue("all")} onFocus={() => prefetchQueue("all")} onClick={() => selectQueue("all")}>All jobs</button>
            </div>
            <div className="results-heading">
              {defaults?.country && <span title="Country from onboarding applies across all providers, including company boards. Unspecified locations remain available for review.">{defaults.country} · all sources</span>}
              <span>{loading ? "Looking…" : `${total} ${total === 1 ? "job" : "jobs"} to review`}</span>{deferredSearch && <span>for “{deferredSearch}”</span>}
            </div>
            {notice && <div className="action-notice transient-notice">{noticeContent}</div>}
            {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
            {queueError && <ErrorMessage message={queueError} retry={() => setQueueRevision((value) => value + 1)} />}
            {loading ? <LoadingRows label="Loading jobs" /> : queueError ? null : jobs.length ? <div className="job-list">
              {jobs.map((job) => <JobRow key={job.id} job={job} selected={selected?.id === job.id} onOpen={(origin) => openJob(job, origin)} />)}
              {total > jobs.length && <p className="result-limit">Showing the newest {jobs.length} matches. Search or filter to narrow the list.</p>}
            </div> : <EmptyState title={emptyState.title} actions={emptyState.actions}>{emptyState.message}</EmptyState>}
          </>}
        </section>

        {selected && <JobDetailPanel job={selected} companyBlocked={selectedCompanyBlocked} companyBusy={companyBusy} pendingAction={pendingAction} queueLoading={loading} onClose={closeJob} onChangeCompany={changeCompany} onDisposition={dispositionSelected} onHide={hideSelected} onScreened={updateQuickScreen} />}
      </div>
    </div>
  );
}
