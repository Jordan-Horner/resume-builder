import { useEffect, useState } from "react";
import {
  getJobSources, getScrapeSchedule, saveScrapeSchedule, setJobSource, startJobScan,
  type JobSourcesState, type ScrapeSchedule,
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
  const [saved, setSaved] = useState<ScrapeSchedule | null>(null);
  const [enabled, setEnabled] = useState(true);
  const [times, setTimes] = useState<string[]>(PRESETS.once);
  const [frequency, setFrequency] = useState<Frequency>("once");
  const [newTime, setNewTime] = useState("12:00");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");

  useEffect(() => {
    let active = true;
    getScrapeSchedule().then((result) => {
      if (!active) return;
      setSaved(result);
      setEnabled(result.enabled);
      setTimes(result.times);
      setFrequency(frequencyFor(result.times));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load scrape schedule");
    });
    return () => { active = false; };
  }, []);

  function chooseFrequency(next: Frequency) {
    setFrequency(next);
    setNotice("");
    if (next !== "custom") setTimes(PRESETS[next]);
  }

  function addTime() {
    if (!times.includes(newTime)) setTimes([...times, newTime].sort());
  }

  async function save() {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      const result = await saveScrapeSchedule(enabled, times);
      setSaved(result);
      setEnabled(result.enabled);
      setTimes(result.times);
      setFrequency(frequencyFor(result.times));
      setNotice(result.enabled ? "Schedule saved." : "Automatic scraping is off. Your times are saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save scrape schedule");
    } finally {
      setBusy(false);
    }
  }

  const changed = saved
    ? enabled !== saved.enabled || times.join(",") !== saved.times.join(",")
    : true;
  return <section className="scrape-schedule" aria-labelledby="scrape-schedule-title">
    <div className="schedule-heading">
      <div><h2 id="scrape-schedule-title">Automatic scraping</h2><p>Keep your job queue fresh without starting each search yourself.</p></div>
      <label className="source-toggle"><span>{enabled ? "On" : "Off"}</span><input type="checkbox" role="switch" aria-label="Automatic scraping" checked={enabled} onChange={(event) => { setEnabled(event.target.checked); setNotice(""); }} /></label>
    </div>
    <div className={enabled ? "schedule-controls" : "schedule-controls disabled"} aria-disabled={!enabled}>
      <div><span className="schedule-label">How often</span><div className="schedule-presets" role="group" aria-label="Scrape frequency">
        {(["once", "twice", "custom"] as Frequency[]).map((item) => <button key={item} type="button" className={frequency === item ? "active" : ""} disabled={!enabled} onClick={() => chooseFrequency(item)}>{item === "once" ? "Once daily" : item === "twice" ? "Twice daily" : "Custom"}</button>)}
      </div></div>
      <div><span className="schedule-label">Run at</span><div className="schedule-times">
        {times.map((value) => <span className="time-chip" key={value}>{clockLabel(value)}{frequency === "custom" && times.length > 1 && <button type="button" aria-label={`Remove ${clockLabel(value)}`} disabled={!enabled} onClick={() => setTimes(times.filter((item) => item !== value))}>×</button>}</span>)}
        {frequency === "custom" && <span className="add-time"><input aria-label="New scrape time" type="time" value={newTime} disabled={!enabled} onChange={(event) => setNewTime(event.target.value)} /><button type="button" disabled={!enabled || times.includes(newTime)} onClick={addTime}>Add time</button></span>}
      </div></div>
    </div>
    {saved && <div className="schedule-summary">
      <span><small>Time zone</small>{saved.timezone}</span>
      <span><small>Next scrape</small>{enabled ? dateLabel(saved.next_run, saved.timezone) : "Paused"}</span>
      <span className={`scheduler-state ${saved.service_status}`}><small>Service</small>Scheduler {saved.service_status}</span>
    </div>}
    {saved?.service_status === "offline" && <p className="schedule-warning">The schedule is saved, but it will not run until the automation service is started.</p>}
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
    async function refresh() {
      try { const next = await getJobSources(); if (active) setData(next); }
      catch (reason) { if (active) setError(reason instanceof Error ? reason.message : "Could not load job sources"); }
    }
    void refresh();
    const timer = window.setInterval(refresh, 4000);
    return () => { active = false; window.clearInterval(timer); };
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
