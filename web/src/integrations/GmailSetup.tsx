import { useEffect, useState } from "react";
import { beginGmailAuthorization, getGmailSetup } from "../api";
import type { GmailSetup as GmailSetupState } from "../types";

export function GmailSetup({ connected }: { connected: boolean }) {
  const [setup, setSetup] = useState<GmailSetupState | null>(null);
  const [step, setStep] = useState(() => Math.max(0, Math.min(5, Number(window.localStorage.getItem("resume-builder.gmail-step") || "0"))));
  const [file, setFile] = useState<File | null>(null);
  const [authorizationUrl, setAuthorizationUrl] = useState("");
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    getGmailSetup().then(setSetup).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load Gmail setup.")).finally(() => setLoading(false));
  }, []);

  function move(next: number) {
    const value = Math.max(0, Math.min((setup?.steps.length || 1) - 1, next));
    setStep(value);
    window.localStorage.setItem("resume-builder.gmail-step", String(value));
  }

  async function authorize() {
    if (!file) return;
    setSaving(true); setError(""); setAuthorizationUrl("");
    try { setAuthorizationUrl((await beginGmailAuthorization(file)).authorization_url); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not read the Google OAuth file."); }
    finally { setSaving(false); }
  }

  if (loading) return <div className="integration-setup integration-loading" role="status">Loading Gmail setup…</div>;
  if (!setup) return <div className="integration-setup"><p className="error-text" role="alert">{error || "Gmail setup is unavailable."}</p></div>;
  if (connected || setup.connected) return <div className="integration-setup integration-connected-copy"><strong>Gmail is connected with read-only access.</strong><p>{setup.privacy}</p></div>;
  const current = setup.steps[step];
  return <div className="integration-setup guided-integration gmail-setup">
    <div className="integration-privacy"><strong>Private by design</strong><p>{setup.privacy}</p></div>
    <div className="setup-progress" aria-label={`Gmail setup, step ${current.number} of ${current.total}`}><span>Step {current.number} of {current.total}</span><progress value={current.number} max={current.total} /></div>
    <div className="setup-step"><h3>{current.title}</h3><p>{current.instruction}</p><a className="secondary-button external-setup-link" href={current.link} target="_blank" rel="noreferrer">{current.link_label} ↗</a></div>
    {current.number === current.total && <div className="credential-upload">
      <label htmlFor="gmail-oauth-file">Google OAuth JSON file</label><p>Choose the Desktop OAuth file you just downloaded. Resume Builder validates it without saving a copy.</p>
      <input id="gmail-oauth-file" type="file" accept="application/json,.json" onChange={(event) => { setFile(event.target.files?.[0] || null); setAuthorizationUrl(""); setError(""); }} disabled={saving} />
      <button className="primary-button" onClick={() => void authorize()} disabled={!file || saving}>{saving ? "Preparing Google…" : "Use this file"}</button>
      {authorizationUrl && <div className="authorization-ready" role="status"><strong>Your file is valid.</strong><p>Continue to Google to grant read-only access. You’ll return here when it’s done.</p><a className="primary-button" href={authorizationUrl}>Continue to Google</a></div>}
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
    <div className="setup-navigation"><button className="text-button" onClick={() => move(step - 1)} disabled={step === 0}>Back</button>{step < setup.steps.length - 1 && <button className="primary-button" onClick={() => move(step + 1)}>Next step</button>}</div>
  </div>;
}
