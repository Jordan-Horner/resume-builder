import { useEffect, useState } from "react";
import { getJobSources, setJobSource, startJobScan, type JobSourcesState } from "../api";

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
    void refresh(); const timer = window.setInterval(refresh, 4000);
    return () => { active = false; window.clearInterval(timer); };
  }, []);
  async function change(action: () => Promise<JobSourcesState>) {
    setBusy(true); setError("");
    try { setData(await action()); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save job sources"); }
    finally { setBusy(false); }
  }
  const running = data?.scan.status === "running";
  return <section className="job-sources" aria-labelledby="job-sources-title">
    <h2 id="job-sources-title">Scrapers</h2>
    <p>Choose where to look. Changes save automatically; searches start only when you ask.</p>
    {!data && !error && <p role="status">Loading sources…</p>}
    {data?.providers.map((provider) => <label className="job-source-row" key={provider.id}>
      <span><strong>{provider.name}</strong><small>{provider.detail}</small></span>
      <span className="source-toggle"><span>{provider.enabled ? "On" : "Off"}</span><input type="checkbox" role="switch" aria-label={provider.name} checked={provider.enabled} disabled={busy || running} onChange={(event) => { const enabled = event.target.checked; void change(() => setJobSource(provider.id, enabled)); }} /></span>
    </label>)}
    {error && <p role="alert" className="onboarding-error">{error} <button className="text-button" onClick={() => void change(getJobSources)}>Retry</button></p>}
    <div className="source-scan-actions"><button className="onboarding-primary" disabled={busy || running || !data?.providers.some((provider) => provider.enabled)} onClick={() => void change(startJobScan)}>{running ? "Finding jobs…" : busy ? "Saving…" : "Find jobs now"}</button><small>Uses your saved roles and preferences. Does not enable a schedule.</small></div>
    {data && data.scan.status !== "idle" && <div aria-live="polite" className="source-scan-result">
      <p>{data.scan.message}</p>
      {data.scan.new_jobs !== undefined && <p>{data.scan.new_jobs} new jobs added. <a href="/jobs">View jobs →</a></p>}
      {data.scan.errors?.map((item, index) => <p key={index}>{item.provider}: {item.message}</p>)}
    </div>}
  </section>;
}
