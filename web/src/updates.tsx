import { createContext, useContext, useEffect, useState, type ReactNode } from "react";
import { getSystemStatus, getUpdateStatus, type SystemStatus, type UpdateStatus } from "./api";

const UpdateContext = createContext<{ status: UpdateStatus | null; error: string; dismissed: string | null; dismiss: () => void }>({ status: null, error: "", dismissed: null, dismiss: () => undefined });
const DISMISSED_KEY = "resume-builder.dismissed-update.v1";

export function UpdateProvider({ children }: { children: ReactNode }) {
  const [status, setStatus] = useState<UpdateStatus | null>(null);
  const [error, setError] = useState("");
  const [dismissed, setDismissed] = useState(() => {
    try { return localStorage.getItem(DISMISSED_KEY); }
    catch (reason) { console.warn("Could not restore update dismissal", reason); return null; }
  });
  function dismiss() {
    if (!status?.latest_revision) return;
    setDismissed(status.latest_revision);
    try { localStorage.setItem(DISMISSED_KEY, status.latest_revision); }
    catch (reason) { console.warn("Could not save update dismissal", reason); }
  }
  useEffect(() => {
    let active = true;
    let timer: ReturnType<typeof setTimeout>;
    async function check() {
      try {
        const next = await getUpdateStatus();
        if (active) { setStatus(next); setError(""); }
      } catch (reason) {
        if (active) setError(reason instanceof Error ? reason.message : "Unable to check for updates.");
      } finally {
        if (active) timer = setTimeout(() => void check(), 5 * 60 * 1000);
      }
    }
    void check();
    return () => { active = false; clearTimeout(timer); };
  }, []);
  return <UpdateContext.Provider value={{ status, error, dismissed, dismiss }}>{children}</UpdateContext.Provider>;
}

export function UpdateNotice() {
  const { status, error, dismissed } = useContext(UpdateContext);
  if (error || status?.status !== "update_available" || !status.latest_revision || dismissed === status.latest_revision) return null;
  return <a className="update-indicator" href="/settings/about" aria-label="Update available — view About" title="Update available">
    <span className="update-dot" aria-hidden="true" /><span className="update-label">Update available</span>
  </a>;
}

export function AboutSection() {
  const { status, error, dismissed, dismiss } = useContext(UpdateContext);
  const [system, setSystem] = useState<SystemStatus | null>(null);
  const [systemError, setSystemError] = useState("");
  useEffect(() => {
    let active = true;
    getSystemStatus().then((next) => {
      if (active) { setSystem(next); setSystemError(""); }
    }).catch(() => { if (active) setSystemError("System status is temporarily unavailable."); });
    return () => { active = false; };
  }, []);
  return <section className="about-panel" aria-labelledby="about-heading">
    <h2 id="about-heading">About Resume Builder</h2>
    <p>Your private career workspace.</p>
    {!status && !error && <p role="status">Checking version…</p>}
    {error && <p role="alert">Unable to check for updates. The next check will retry automatically.</p>}
    {status && <>
      <dl className="about-details">
        <div><dt>Version</dt><dd>{status.version} <span className={`version-status ${error ? "unavailable" : status.status}`}>{error ? "Unable to check" : status.status === "up_to_date" ? "Up to date" : status.status === "update_available" ? "Update available" : status.status === "development" ? "Development build" : status.status === "ahead" ? "Ahead of channel" : "Unable to check"}</span></dd></div>
        <div><dt>Channel</dt><dd>{status.channel === "main" ? "Main · rolling builds" : "Local development"}</dd></div>
        <div><dt>Installed build</dt><dd>{status.revision.slice(0, 12)}</dd></div>
        <div><dt>Last successful check</dt><dd>{status.last_success_at ? new Date(status.last_success_at).toLocaleString() : "Not checked"}</dd></div>
      </dl>
      {!error && status.status === "unavailable" && <p role="status">{status.message}</p>}
      {status.status !== "development" && <p className="update-help">Checks are cached for one hour. Failed checks retry within five minutes. Updates are installed through Docker on the host—not in this app.</p>}
      <div className="about-links"><a href={status.release_url} target="_blank" rel="noreferrer">View release ↗</a><a href="https://github.com/Jordan-Horner/resume-builder/blob/main/docs/container-deployment.md" target="_blank" rel="noreferrer">Docker update instructions ↗</a></div>
      {!error && status.status === "update_available" && status.latest_revision && <p className="update-dismissal">{dismissed === status.latest_revision ? "Navigation notice hidden for this build. Future updates will still appear." : <button className="text-button" onClick={dismiss}>Dismiss this update notice</button>}</p>}
    </>}
    <div className="system-health-heading">
      <h3>System status</h3>
      {system && <span className={`system-summary ${system.status}`}>{system.status === "healthy" ? "All systems ready" : "Needs attention"}</span>}
    </div>
    {!system && !systemError && <p role="status">Checking services…</p>}
    {systemError && <p role="alert">{systemError}</p>}
    {system && <dl className="system-health-list">
      {system.components.map((component) => <div key={component.id}>
        <dt><span className={`service-dot ${component.status}`} aria-hidden="true" />{component.name}</dt>
        <dd>{component.detail}</dd>
      </div>)}
    </dl>}
  </section>;
}
