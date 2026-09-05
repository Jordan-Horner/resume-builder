import { useDeferredValue, useEffect, useState } from "react";
import { activateJobSearch, getJobs, markJobApplied, markJobNotInterested, getBlockedCompanies, setCompanyBlocked, getJobFilterDefaults, getSearchPreferences, getJobSources, startJobScan } from "../api";
import { ArrowIcon, EmptyState, ErrorMessage, LoadingRows, SearchIcon } from "../components";
import { EMPTY_FILTERS, persistView, restoreView } from "../viewPreferences";
import { JobViewFilters } from "../JobViewFilters";
import type { Job, JobFilters, SearchPreferences, ViewFilters } from "../types";


const DATE_FILTERS = [
  { label: "Any date", value: 0 },
  { label: "Last 24 hours", value: 1 },
  { label: "Last 3 days", value: 3 },
  { label: "Last 7 days", value: 7 },
  { label: "Last 2 weeks", value: 14 },
  { label: "Last 30 days", value: 30 },
] as const;


function formatDate(value: string | null) {
  if (!value) return "Recently found";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Recently found";
  return new Intl.DateTimeFormat(undefined, { month: "short", day: "numeric" }).format(date);
}

function formatSalary(job: Job) {
  if (!job.salary_min && !job.salary_max) return null;
  const currency = job.salary_currency || "USD";
  const format = (value: number) => new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    maximumFractionDigits: 0,
    notation: value >= 100_000 ? "compact" : "standard",
  }).format(value);
  const amount = job.salary_min && job.salary_max
    ? `${format(job.salary_min)}–${format(job.salary_max)}`
    : format((job.salary_min || job.salary_max)!);
  return job.salary_interval ? `${amount} / ${job.salary_interval}` : amount;
}

function modeLabel(modes: string[]) {
  const labels = modes.filter((mode) => mode !== "unknown").map((mode) => (
    mode === "onsite" ? "On-site" : mode[0].toUpperCase() + mode.slice(1)
  ));
  return labels.join(" + ") || "Work mode not listed";
}

function compactCurrency(value: number, currency: string) {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 0,
  }).format(value);
}

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
  const [reloadKey, setReloadKey] = useState(0);
  const [pendingAction, setPendingAction] = useState<"not-interested" | "applied" | null>(null);
  const [notice, setNotice] = useState("");
  const [blockedCompanies, setBlockedCompanies] = useState<string[]>([]);
  const [companyBusy, setCompanyBusy] = useState(false);
  useEffect(() => {
    let active = true;
    getJobFilterDefaults().then((value) => {
      if (!active) return;
      setDefaults(value);
      try { const restored = restoreView(value); setFilters(restored.filters); setPreferencesUpdated(!!restored.updated); }
      catch (reason) {
        setFilters({ ...EMPTY_FILTERS, view: value });
        setError(reason instanceof Error ? reason.message : "Could not restore saved filters.");
      }
    }).catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load job preferences."); });
    return () => { active = false; };
  }, [reloadKey]);

  useEffect(() => {
    let active = true;
    getSearchPreferences().then((value) => { if (active) setSearchPreferences(value); }).catch(() => undefined);
    return () => { active = false; };
  }, [reloadKey]);
  const companyKey = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();
  const selectedCompanyBlocked = !!selected && blockedCompanies.some((company) => companyKey(company) === companyKey(selected.company));

  useEffect(() => {
    let active = true;
    getBlockedCompanies().then((result) => { if (active) setBlockedCompanies(result.companies); }).catch((reason) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load blocked companies"); });
    return () => { active = false; };
  }, [reloadKey]);

  async function changeCompany(company: string, blocked: boolean) {
    if (companyBusy || pendingAction) return;
    setCompanyBusy(true); setError("");
    try {
      const result = await setCompanyBlocked(company, blocked);
      setBlockedCompanies(result.companies);
      setNotice(`${company} ${blocked ? "blocked" : "unblocked"}.`);
      setReloadKey((key) => key + 1);
    } catch (reason) { setError(reason instanceof Error ? reason.message : `Could not ${blocked ? "block" : "unblock"} ${company}. Try again.`); }
    finally { setCompanyBusy(false); }
  }

  useEffect(() => {
    if (!defaults) return;
    try { persistView(filters, defaults); }
    catch { setError("Your browser could not save these filters. They will last only while this page is open."); }
  }, [filters, defaults]);

  useEffect(() => {
    let active = true;
    if (!defaults) return;
    setLoading(true);
    getJobs(deferredFilters)
      .then((payload) => {
        if (!active) return;
        setJobs(payload.jobs);
        setTotal(payload.count);
        setReviewableTotal(payload.reviewable_count);
        // Keep the open posting available for review and immediate unblocking.
      })
      .catch((reason: unknown) => active && setError(reason instanceof Error ? reason.message : "Could not load jobs"))
      .finally(() => active && setLoading(false));
    return () => { active = false; };
  }, [deferredFilters, defaults, reloadKey]);

  function openJob(job: Job) {
    setSelected(job);
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
    try { await activateJobSearch(); setReloadKey((key) => key + 1); setNotice("Searches activated. You can find jobs now."); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not activate your searches."); }
  }

  function closeJob() {
    setSelected(null);
  }

  async function dispositionSelected(disposition: "not-interested" | "applied") {
    if (!selected || pendingAction || companyBusy) return;
    const job = selected;
    setPendingAction(disposition);
    setError("");
    try {
      if (disposition === "applied") await markJobApplied(job.id);
      else await markJobNotInterested(job.id);
      setJobs((current) => current.filter((item) => item.id !== job.id));
      setTotal((current) => Math.max(0, current - 1));
      setSelected(null);
      setNotice(
        disposition === "applied"
          ? `${job.title} moved to Applications.`
          : `${job.title} removed from your job inventory.`,
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update this job");
    } finally {
      setPendingAction(null);
    }
  }

  const emptyState = searchPreferences?.status === "ready_to_activate"
    ? {
        title: "Finish setting up your search",
        message: "Activate your saved roles before searching.",
        actions: <button className="primary-button" onClick={() => void finishSetup()}>Finish setup</button>,
      }
    : reviewableTotal === 0
      ? {
          title: "Find your first jobs",
          message: "Search your enabled sources using your saved roles and preferences.",
          actions: <><button className="primary-button" disabled={scanning} onClick={() => void runManualScan()}>{scanning ? "Finding jobs…" : "Find jobs now"}</button><a className="empty-state-link" href="/settings/search-preferences">Edit preferences</a></>,
        }
      : {
          title: "No jobs match these filters",
          message: `${reviewableTotal} reviewable ${reviewableTotal === 1 ? "job is" : "jobs are"} hidden by your current filters.`,
          actions: <><button className="primary-button" onClick={() => defaults && setFilters({ ...EMPTY_FILTERS, view: defaults })}>Reset filters</button><button className="empty-state-link" onClick={() => setFilters(EMPTY_FILTERS)}>Clear all</button></>,
        };

  const hasNoInventory = !loading && reviewableTotal === 0;
  const savedRoles = searchPreferences?.titles || [];
  const savedModes = searchPreferences?.work_modes || [];
  const savedCompensation = searchPreferences?.compensation;
  const roleSummary = savedRoles.length
    ? `${savedRoles.length} ${savedRoles.length === 1 ? "role" : "roles"}`
    : "No roles saved";
  const locationSummary = [
    searchPreferences?.country,
    savedModes.length ? modeLabel(savedModes) : null,
  ].filter(Boolean).join(" · ") || "Any location";
  const compensationSummary = savedCompensation && !savedCompensation.skipped && savedCompensation.minimum
    ? `${compactCurrency(savedCompensation.minimum, savedCompensation.currency || "USD")}+ minimum`
    : "Any compensation";

  return (
    <div className="page jobs-page">
      {!hasNoInventory && <section className="search-tools jobs-search-tools" aria-label="Search and filters">
        <label className="search-field">
          <SearchIcon />
          <span className="sr-only">Search jobs to review</span>
          <input
            type="search"
            disabled={!defaults}
            value={search}
            onChange={(event) => setFilters({ ...filters, search: event.target.value })}
            placeholder="Title, skill or company"
          />
        </label>
        <label className="search-field location-search-field">
          <svg aria-hidden="true" viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" strokeWidth="2"><path d="M20 10c0 6-8 12-8 12S4 16 4 10a8 8 0 1 1 16 0Z" /><circle cx="12" cy="10" r="3" /></svg>
          <span className="sr-only">State, city or region</span>
          <input aria-label="State, city or region" type="search" disabled={!defaults} value={filters.view?.locations.join("; ") || ""} placeholder="State, city or region" title="Optional narrowing for on-site and hybrid jobs. Remote jobs remain in your country scope." onChange={(event) => setFilters({ ...filters, view: { ...filters.view!, locations: event.target.value ? [event.target.value] : [] } })} />
        </label>
        <select
          value={dateDays}
          onChange={(event) => setFilters({ ...filters, dateDays: Number(event.target.value) as typeof dateDays })}
          aria-label="Date posted"
        >
          {DATE_FILTERS.map((filter) => <option key={filter.value} value={filter.value}>{filter.label}</option>)}
        </select>
        {!defaults && <span role="status">Loading preferences…</span>}
        {defaults && filters.view && <JobViewFilters value={filters.view} onChange={(view) => setFilters({ ...filters, view })} reset={() => setFilters({ ...EMPTY_FILTERS, view: defaults })} clear={() => setFilters(EMPTY_FILTERS)} />}
      </section>}
      {preferencesUpdated && defaults && <p className="action-notice">Your saved preferences changed. Custom filters were kept. <button className="text-button" onClick={() => { setFilters({ ...EMPTY_FILTERS, view: defaults }); setPreferencesUpdated(false); }}>Apply updated preferences</button></p>}

      <div className={selected ? "jobs-layout detail-open" : "jobs-layout"}>
        <section className="job-results" aria-live="polite">
          {hasNoInventory && !error ? (
            <div className="first-search" aria-labelledby="first-search-title">
              <p className="first-search-kicker">Your search is ready</p>
              <h1 id="first-search-title">Build your job queue</h1>
              <p className="first-search-intro">Search every enabled source using the preferences you already chose.</p>
              <dl className="first-search-summary">
                <div><dt>Searching for</dt><dd>{roleSummary}</dd></div>
                <div><dt>Where</dt><dd>{locationSummary}</dd></div>
                <div><dt>Pay</dt><dd>{compensationSummary}</dd></div>
              </dl>
              <div className="first-search-actions">
                {searchPreferences?.status === "ready_to_activate" ? (
                  <button className="primary-button" onClick={() => void finishSetup()}>Finish setup</button>
                ) : (
                  <button className="primary-button" disabled={scanning} onClick={() => void runManualScan()}>{scanning ? "Searching sources…" : "Find jobs now"}</button>
                )}
                <a className="empty-state-link" href="/settings/search-preferences">Review search settings</a>
              </div>
              {notice && <p className="first-search-notice" role="status">{notice}</p>}
            </div>
          ) : <>
          <div className="results-heading">
            {defaults?.country && <span title="Country from onboarding applies across all providers, including company boards. Unspecified locations remain available for review.">{defaults.country} · all sources</span>}
            <span>{loading ? "Looking…" : `${total} ${total === 1 ? "job" : "jobs"} to review`}</span>
            {deferredSearch && <span>for “{deferredSearch}”</span>}
          </div>
          {notice && <p className="action-notice" role="status">{notice}</p>}
          {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
          {loading ? <LoadingRows /> : jobs.length ? (
            <div className="job-list">
              {jobs.map((job) => (
                <button
                  className={selected?.id === job.id ? "job-row selected" : "job-row"}
                  key={job.id}
                  onClick={() => openJob(job)}
                >
                  <span className="job-row-main">
                    <span className="job-title-line"><strong>{job.title}</strong></span>
                    <span className="company">{job.company}</span>
                    <span className="job-meta"><span>{job.location}</span><i /><span>{modeLabel(job.work_modes)}</span></span>
                  </span>
                  <span className="job-row-side">
                    {formatSalary(job) && <span className="row-salary">{formatSalary(job)}</span>}
                    <span>{formatDate(job.posted_at || job.first_seen_at)}</span>
                    <ArrowIcon />
                  </span>
                </button>
              ))}
              {total > jobs.length && <p className="result-limit">Showing the newest {jobs.length} matches. Search or filter to narrow the list.</p>}
            </div>
          ) : (
            <EmptyState title={emptyState.title} actions={emptyState.actions}>{emptyState.message}</EmptyState>
          )}
          </>}
        </section>

        {selected && (
          <aside className="job-detail" aria-label={`${selected.title} details`}>
            <div className="detail-summary">
              <button className="detail-close" onClick={closeJob} aria-label="Close job details">×</button>
              <p className="eyebrow">{selected.providers.join(" · ") || "Job listing"}</p>
              <h2>{selected.title}</h2>
              <div className="detail-company-actions"><p className="detail-company">{selected.company}</p><button className="secondary-button" disabled={companyBusy || !!pendingAction || loading || !selected.company.trim()} onClick={() => void changeCompany(selected.company, !selectedCompanyBlocked)}>{companyBusy ? "Saving…" : selectedCompanyBlocked ? "Unblock company" : "Block company"}</button></div>
              <div className="detail-tags">
                <span>{modeLabel(selected.work_modes)}</span>
                <span>{selected.location}</span>
                {formatSalary(selected) && <span>{formatSalary(selected)}</span>}
              </div>
              <div className="job-actions" aria-label="Update job status">
                {selected.url && (
                  <a className="secondary-button original-link" href={selected.url} target="_blank" rel="noreferrer">
                    Open posting <ArrowIcon />
                  </a>
                )}
                <button
                  className="primary-button apply-button"
                  onClick={() => dispositionSelected("applied")}
                  disabled={pendingAction !== null}
                >
                  {pendingAction === "applied" ? "Moving to Applications…" : "Mark as applied"}
                </button>
                <button
                  className="secondary-button reject-button"
                  onClick={() => dispositionSelected("not-interested")}
                  disabled={pendingAction !== null}
                >
                  {pendingAction === "not-interested" ? "Removing…" : "Not interested"}
                </button>
              </div>
            </div>
            <div className="job-description">
              {selected.description ? selected.description.split(/\n+/).map((paragraph, index) => (
                paragraph.trim() && <p key={index}>{paragraph}</p>
              )) : <p>No description was included with this listing.</p>}
            </div>
          </aside>
        )}
      </div>
    </div>
  );
}
