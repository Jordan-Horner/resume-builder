import { useEffect, useState } from "react";
import {
  getJobSources, getScrapeSchedule, getScreeningBackfill, saveScrapeSchedule,
  setJobSource, startJobScan, startScreeningBackfill,
  type JobSourcesState, type ScrapeSchedule, type ScreeningBackfillState,
} from "../api";

type Frequency = "once" | "twice" | "custom";
const PRESETS: Record<Exclude<Frequency, "custom">, string[]> = {
  once: ["08:00"],
  twice: ["08:00", "17:00"],
};

function frequencyFor(times: string[]): Frequency {
  const value = [...times].sort().join(",");
  if (value === PRESETS.once.join(",")) return "once";
  if (value === PRESETS.twice.join(",")) return "twice";
  return "custom";
}

function clockLabel(value: string): string {
  const [hour, minute] = value.split(":").map(Number);
  const suffix = hour >= 12 ? "PM" : "AM";
  return `${hour % 12 || 12}:${String(minute).padStart(2, "0")} ${suffix}`;
}

function dateLabel(value: string | null, timezone: string): string {
  if (!value) return "Not scheduled";
  return new Intl.DateTimeFormat(undefined, {
    weekday: "short", hour: "numeric", minute: "2-digit", timeZone: timezone,
  }).format(new Date(value));
}

function ScheduleEditor() {
  const [retry, setRetry] = useState(0);
  const [saved, setSaved] = useState<ScrapeSchedule | null>(null);
  const [enabled, setEnabled] = useState(false);
  const [times, setTimes] = useState<string[]>([]);
  const [frequency, setFrequency] = useState<Frequency>("once");
  const [newTime, setNewTime] = useState("12:00");
  const [screeningEnabled, setScreeningEnabled] = useState(false);
  const [screeningMaxJobs, setScreeningMaxJobs] = useState(6);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [backfill, setBackfill] = useState<ScreeningBackfillState | null>(null);
  const [backfillBusy, setBackfillBusy] = useState(false);

  useEffect(() => {
    let active = true;
    setError("");
    getScrapeSchedule().then((result) => {
      if (!active) return;
      setSaved(result);
      setEnabled(result.enabled);
      setTimes(result.times);
      setFrequency(frequencyFor(result.times));
      setScreeningEnabled(result.screening_enabled);
      setScreeningMaxJobs(result.screening_max_jobs);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load scrape schedule");
    });
    return () => { active = false; };
  }, [retry]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    const refresh = async () => {
      try {
        const result = await getScreeningBackfill();
        if (!active) return;
        setBackfill(result);
        if (result.status === "running") timer = window.setTimeout(refresh, 2000);
      } catch (reason) {
        if (active) {
          setBackfill(null);
          setError(reason instanceof Error ? reason.message : "Could not load screening status");
        }
      }
    };
    void refresh();
    return () => { active = false; if (timer !== undefined) window.clearTimeout(timer); };
  }, []);

  async function runBackfill() {
    if (backfillBusy || backfill?.status === "running") return;
    setBackfillBusy(true);
    setError("");
    try {
      const result = await startScreeningBackfill();
      setBackfill(result);
      const poll = async () => {
        try {
          const next = await getScreeningBackfill();
          setBackfill(next);
          if (next.status === "running") window.setTimeout(() => void poll(), 2000);
        } catch (reason) {
          setError(reason instanceof Error ? reason.message : "Could not read screening progress");
        }
      };
      if (result.status === "running") window.setTimeout(() => void poll(), 1000);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not start screening");
    } finally {
      setBackfillBusy(false);
    }
  }

  function chooseFrequency(next: Frequency) {
    setFrequency(next);
    setNotice("");
    if (next !== "custom") setTimes(PRESETS[next]);
  }

  function addTime() {
    if (!times.includes(newTime)) setTimes([...times, newTime].sort());
  }

  async function save() {
    if (!saved || busy) return;
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await saveScrapeSchedule(enabled, times, screeningEnabled, screeningMaxJobs);
      setSaved(result);
      setEnabled(result.enabled);
      setTimes(result.times);
      setFrequency(frequencyFor(result.times));
      setScreeningEnabled(result.screening_enabled);
      setScreeningMaxJobs(result.screening_max_jobs);
      setNotice(result.enabled ? "Schedule saved." : "Automatic scraping is off. Your times are saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save scrape schedule");
    } finally {
      setBusy(false);
    }
  }

  async function toggleAutomation(next: boolean) {
    if (!saved || busy) return;
    const previous = enabled;
    setEnabled(next);
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await saveScrapeSchedule(next, times, screeningEnabled, screeningMaxJobs);
      setSaved(result);
      setEnabled(result.enabled);
      setTimes(result.times);
      setFrequency(frequencyFor(result.times));
      setScreeningEnabled(result.screening_enabled);
      setScreeningMaxJobs(result.screening_max_jobs);
      setNotice(result.enabled ? "Automatic scraping started." : "Automatic scraping stopped. Manual searches are still available.");
    } catch (reason) {
      setEnabled(previous);
      setError(reason instanceof Error ? reason.message : "Could not change automatic scraping");
    } finally {
      setBusy(false);
    }
  }

  if (!saved) return <section className="scrape-schedule"><h2>Automatic scraping</h2>{error ? <p role="alert">{error} <button onClick={() => setRetry((value) => value + 1)}>Retry schedule</button></p> : <p role="status">Loading schedule…</p>}</section>;

  const changed = saved
    ? enabled !== saved.enabled
      || times.join(",") !== saved.times.join(",")
      || screeningEnabled !== saved.screening_enabled
      || screeningMaxJobs !== saved.screening_max_jobs
    : true;
  return <section className="scrape-schedule" aria-labelledby="scrape-schedule-title">
    <div className="schedule-heading">
      <div><h2 id="scrape-schedule-title">Automatic scraping</h2><p>Keep your job queue fresh without starting each search yourself.</p></div>
      <label className="source-toggle"><span>{enabled ? "On" : "Off"}</span><input type="checkbox" role="switch" aria-label="Automatic scraping" checked={enabled} disabled={busy} onChange={(event) => void toggleAutomation(event.target.checked)} /></label>
    </div>
    <div className={enabled ? "schedule-controls" : "schedule-controls disabled"} aria-disabled={!enabled || busy}>
      <div><span className="schedule-label">How often</span><div className="schedule-presets" role="group" aria-label="Scrape frequency">
        {(["once", "twice", "custom"] as Frequency[]).map((item) => <button key={item} type="button" className={frequency === item ? "active" : ""} disabled={!enabled || busy} onClick={() => chooseFrequency(item)}>{item === "once" ? "Once daily" : item === "twice" ? "Twice daily" : "Custom"}</button>)}
      </div></div>
      <div><span className="schedule-label">Run at</span><div className="schedule-times">
        {times.map((value) => <span className="time-chip" key={value}>{clockLabel(value)}{frequency === "custom" && times.length > 1 && <button type="button" aria-label={`Remove ${clockLabel(value)}`} disabled={!enabled || busy} onClick={() => setTimes(times.filter((item) => item !== value))}>×</button>}</span>)}
        {frequency === "custom" && <span className="add-time"><input aria-label="New scrape time" type="time" value={newTime} disabled={!enabled || busy} onChange={(event) => setNewTime(event.target.value)} /><button type="button" disabled={!enabled || busy || !newTime || times.includes(newTime)} onClick={addTime}>Add time</button></span>}
      </div></div>
    </div>
    {saved && <div className="schedule-summary">
      <span><small>Time zone</small>{saved.timezone}</span>
      <span><small>Next scrape</small>{enabled ? dateLabel(saved.next_run, saved.timezone) : "Paused"}</span>
      <span className={`scheduler-state ${saved.service_status}`}><small>Service</small>{saved.enabled ? `Scheduler ${saved.service_status}` : "Scheduler stopped"}</span>
    </div>}
    {saved?.enabled && saved.service_status === "offline" && <p className="schedule-warning">Automatic scraping could not start. Check Settings → About for service status.</p>}
    <div className="background-screening">
      <div>
        <strong>Background quick screening</strong>
        <p>Automatic runs screen up to {screeningMaxJobs} eligible recommendations. A manual backfill continues in safe batches until the eligible backlog is clear.</p>
        {!saved.screening_available && <p className="screening-setup-note"><a href="/settings/integrations">Connect OpenRouter</a> to turn this on.</p>}
        {backfill && backfill.status !== "idle" && <p className="screening-backfill-status" role="status">{backfill.message}{backfill.status !== "running" && backfill.pending_screening_jobs ? ` ${backfill.pending_screening_jobs} could not be completed automatically.` : ""}</p>}
      </div>
      <div className="background-screening-controls">
        <label><span>Per run</span><select aria-label="Quick screens per run" value={screeningMaxJobs} disabled={busy || !screeningEnabled} onChange={(event) => setScreeningMaxJobs(Number(event.target.value))}>{[3, 6, 10, 15, 25].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>
        <label className="source-toggle"><span>{screeningEnabled ? "On" : "Off"}</span><input type="checkbox" role="switch" aria-label="Background quick screening" checked={screeningEnabled} disabled={busy || !saved.screening_available} onChange={(event) => { setScreeningEnabled(event.target.checked); setNotice(""); }} /></label>
        <button className="secondary-button" disabled={busy || backfillBusy || backfill?.status === "running" || !saved.screening_available || !saved.screening_enabled} onClick={() => void runBackfill()}>{backfill?.status === "running" ? "Screening…" : "Screen all eligible jobs"}</button>
      </div>
    </div>
    {error && <p role="alert" className="onboarding-error">{error}</p>}
    {notice && <p role="status" className="schedule-notice">{notice}</p>}
    <button className="onboarding-primary schedule-save" disabled={busy || !changed || !times.length} onClick={() => void save()}>{busy ? "Saving…" : "Save schedule"}</button>
  </section>;
}

export function JobSources() {
  const [data, setData] = useState<JobSourcesState | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    async function refresh() {
      try {
        const next = await getJobSources();
        if (active) {
          setData(next);
          setError("");
        }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Could not load job sources");
      } finally {
        if (active) timer = window.setTimeout(refresh, 4000);
      }
    }
    void refresh();
    return () => {
      active = false;
      if (timer !== undefined) window.clearTimeout(timer);
    };
  }, []);
  async function change(action: () => Promise<JobSourcesState>) {
    setBusy(true); setError("");
    try { setData(await action()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save job sources"); }
    finally { setBusy(false); }
  }
  const running = data?.scan.status === "running";
  return <div className="job-sources"><ScheduleEditor /><section className="provider-settings" aria-labelledby="job-sources-title">
    <div className="provider-heading"><div><h2 id="job-sources-title">Sources</h2><p>Choose which job sites are included in manual and scheduled searches.</p></div><button className="onboarding-primary" disabled={busy || running || !data?.providers.some((provider) => provider.enabled)} onClick={() => void change(startJobScan)}>{running ? "Finding jobs…" : "Find jobs now"}</button></div>
    {!data && !error && <p role="status">Loading sources…</p>}
    {data?.providers.map((provider) => <label className="job-source-row" key={provider.id}>
      <span><strong>{provider.name}</strong><small>{provider.detail}</small></span>
      <span className="source-toggle"><span>{provider.enabled ? "On" : "Off"}</span><input type="checkbox" role="switch" aria-label={provider.name} checked={provider.enabled} disabled={busy || running} onChange={(event) => { const sourceEnabled = event.target.checked; void change(() => setJobSource(provider.id, sourceEnabled)); }} /></span>
    </label>)}
    {error && <p role="alert" className="onboarding-error">{error} <button className="text-button" onClick={() => void change(getJobSources)}>Retry</button></p>}
    {data && data.scan.status !== "idle" && <div aria-live="polite" className="source-scan-result"><p>{data.scan.message}</p>{data.scan.new_jobs !== undefined && <p>{data.scan.new_jobs} new jobs added. <a href="/jobs">View jobs →</a></p>}{data.scan.errors?.map((item, index) => <p key={index}>{item.provider}: {item.message}</p>)}</div>}
  </section></div>;
}
