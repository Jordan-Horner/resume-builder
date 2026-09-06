import { useDeferredValue, useEffect, useRef, useState } from "react";
import {
  activateJobSearch, getBlockedCompanies, getJobFilterDefaults, getJobs, getJobSources,
  getSearchPreferences, markJobApplied, markJobNotInterested, setCompanyBlocked, startJobScan,
} from "../api";
import { EmptyState, ErrorMessage, LoadingRows, SearchField } from "../components";
import { JobViewFilters } from "../JobViewFilters";
import { JobDetailPanel } from "../jobs/JobDetailPanel";
import { formatCompactCurrency, formatWorkModes } from "../jobs/jobFormatters";
import { JobRow } from "../jobs/JobRow";
import type { Job, JobFilters, SearchPreferences, ViewFilters } from "../types";
import { EMPTY_FILTERS, persistView, restoreView } from "../viewPreferences";

const DATE_FILTERS = [
  { label: "Any date", value: 0 }, { label: "Last 24 hours", value: 1 },
  { label: "Last 3 days", value: 3 }, { label: "Last 7 days", value: 7 },
  { label: "Last 2 weeks", value: 14 }, { label: "Last 30 days", value: 30 },
] as const;
const companyKey = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

export function JobsPage() {
  const [filters, setFilters] = useState<JobFilters>(EMPTY_FILTERS);
  const [defaults, setDefaults] = useState<ViewFilters | null>(null);
  const [preferencesUpdated, setPreferencesUpdated] = useState(false);
  const deferredFilters = useDeferredValue(filters);
  const { search, dateDays } = filters;
  const deferredSearch = deferredFilters.search;
  const [jobs, setJobs] = useState<Job[]>([]);
  const [total, setTotal] = useState(0);
  const [reviewableTotal, setReviewableTotal] = useState(0);
  const [searchPreferences, setSearchPreferences] = useState<SearchPreferences | null>(null);
  const [scanning, setScanning] = useState(false);
  const [selected, setSelected] = useState<Job | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [queueError, setQueueError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [queueRevision, setQueueRevision] = useState(0);
  const [pendingAction, setPendingAction] = useState<"not-interested" | "applied" | null>(null);
  const [notice, setNotice] = useState("");
  const [blockedCompanies, setBlockedCompanies] = useState<string[]>([]);
  const [companyBusy, setCompanyBusy] = useState(false);
  const selectedOrigin = useRef<HTMLButtonElement | null>(null);
  const results = useRef<HTMLElement | null>(null);
  const focusQueueAfterRefresh = useRef(false);

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
    if (!defaults) return;
    setLoading(true);
    setQueueError("");
    getJobs(deferredFilters).then((payload) => {
      if (!active) return;
      setJobs(payload.jobs);
      setTotal(payload.count);
      setReviewableTotal(payload.reviewable_count);
    }).catch((reason: unknown) => {
      if (active) setQueueError(reason instanceof Error ? reason.message : "Could not load jobs");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [deferredFilters, defaults, reloadKey, queueRevision]);

  useEffect(() => {
    if (loading || !focusQueueAfterRefresh.current) return;
    focusQueueAfterRefresh.current = false;
    (results.current?.querySelector<HTMLButtonElement>(".job-row") || results.current)?.focus();
  }, [jobs, loading]);

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

  async function dispositionSelected(disposition: "not-interested" | "applied") {
    if (!selected || pendingAction || companyBusy) return;
    const job = selected;
    setPendingAction(disposition); setError("");
    try {
      if (disposition === "applied") await markJobApplied(job.id);
      else await markJobNotInterested(job.id);
      setLoading(true);
      focusQueueAfterRefresh.current = true;
      setQueueRevision((value) => value + 1);
      setSelected(null);
      setNotice(disposition === "applied" ? `${job.title} moved to Applications.` : `${job.title} removed from your job inventory.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this job");
    } finally { setPendingAction(null); }
  }

  const emptyState = searchPreferences?.status === "ready_to_activate"
    ? { title: "Finish setting up your search", message: "Activate your saved roles before searching.", actions: <button className="primary-button" onClick={() => void finishSetup()}>Finish setup</button> }
    : reviewableTotal === 0
      ? { title: "Find your first jobs", message: "Search your enabled sources using your saved roles and preferences.", actions: <><button className="primary-button" disabled={scanning} onClick={() => void runManualScan()}>{scanning ? "Finding jobs…" : "Find jobs now"}</button><a className="empty-state-link" href="/settings/search-preferences">Edit preferences</a></> }
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
            {notice && <p className="first-search-notice" role="status">{notice}</p>}
          </div> : <>
            <div className="results-heading">
              {defaults?.country && <span title="Country from onboarding applies across all providers, including company boards. Unspecified locations remain available for review.">{defaults.country} · all sources</span>}
              <span>{loading ? "Looking…" : `${total} ${total === 1 ? "job" : "jobs"} to review`}</span>{deferredSearch && <span>for “{deferredSearch}”</span>}
            </div>
            {notice && <p className="action-notice" role="status">{notice}</p>}
            {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
            {queueError && <ErrorMessage message={queueError} retry={() => setQueueRevision((value) => value + 1)} />}
            {loading ? <LoadingRows label="Loading jobs" /> : queueError ? null : jobs.length ? <div className="job-list">
              {jobs.map((job) => <JobRow key={job.id} job={job} selected={selected?.id === job.id} onOpen={(origin) => openJob(job, origin)} />)}
              {total > jobs.length && <p className="result-limit">Showing the newest {jobs.length} matches. Search or filter to narrow the list.</p>}
            </div> : <EmptyState title={emptyState.title} actions={emptyState.actions}>{emptyState.message}</EmptyState>}
          </>}
        </section>

        {selected && <JobDetailPanel job={selected} companyBlocked={selectedCompanyBlocked} companyBusy={companyBusy} pendingAction={pendingAction} queueLoading={loading} onClose={closeJob} onChangeCompany={changeCompany} onDisposition={dispositionSelected} />}
      </div>
    </div>
  );
}
