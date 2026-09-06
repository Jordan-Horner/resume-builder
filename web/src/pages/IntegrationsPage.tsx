import { useEffect, useState } from "react";
import { beginGmailAuthorization, configureOpenRouter, getGmailSetup, getIntegrations, getTelegramPairing, startTelegramPairing } from "../api";
import { EmptyState, ErrorMessage, LoadingRows } from "../components";
import type { GmailSetup as GmailSetupState, Integration, TelegramPairing } from "../types";

function OpenRouterSetup({ connected, onSaved }: { connected: boolean; onSaved: (message: string) => void }) {
  const [key, setKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");
  async function save() {
    setSaving(true); setError("");
    try {
      const result = await configureOpenRouter(key.trim());
      setKey(""); onSaved(result.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not connect OpenRouter.");
    } finally { setSaving(false); }
  }
  return <form className="integration-setup openrouter-setup" onSubmit={(event) => { event.preventDefault(); void save(); }}>
    <label htmlFor="openrouter-key">{connected ? "Replace API key" : "OpenRouter API key"}</label>
    <p>Stored on your server and never shown again. Existing model and search settings stay unchanged.</p>
    <div className="openrouter-key-entry">
      <input id="openrouter-key" type="password" autoComplete="new-password" spellCheck={false} maxLength={512} placeholder="Paste your API key" value={key} onChange={(event) => setKey(event.target.value)} disabled={saving} required />
      <button className="primary-button" disabled={saving || !key.trim()}>{saving ? "Connecting…" : "Save and connect"}</button>
    </div>
    <a href="https://openrouter.ai/settings/keys" target="_blank" rel="noreferrer">Get an OpenRouter key ↗</a>
    {error && <p className="error-text" role="alert">{error}</p>}
  </form>;
}

function GmailSetup({ connected }: { connected: boolean }) {
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
    try {
      const result = await beginGmailAuthorization(file);
      setAuthorizationUrl(result.authorization_url);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not read the Google OAuth file.");
    } finally { setSaving(false); }
  }

  if (loading) return <div className="integration-setup integration-loading">Loading Gmail setup…</div>;
  if (!setup) return <div className="integration-setup"><p className="error-text" role="alert">{error || "Gmail setup is unavailable."}</p></div>;
  if (connected || setup.connected) return <div className="integration-setup integration-connected-copy"><strong>Gmail is connected with read-only access.</strong><p>{setup.privacy}</p></div>;
  const current = setup.steps[step];
  return <div className="integration-setup guided-integration gmail-setup">
    <div className="integration-privacy"><strong>Private by design</strong><p>{setup.privacy}</p></div>
    <div className="setup-progress" aria-label={`Gmail setup, step ${current.number} of ${current.total}`}>
      <span>Step {current.number} of {current.total}</span><progress value={current.number} max={current.total} />
    </div>
    <div className="setup-step">
      <h3>{current.title}</h3>
      <p>{current.instruction}</p>
      <a className="secondary-button external-setup-link" href={current.link} target="_blank" rel="noreferrer">{current.link_label} ↗</a>
    </div>
    {current.number === current.total && <div className="credential-upload">
      <label htmlFor="gmail-oauth-file">Google OAuth JSON file</label>
      <p>Choose the Desktop OAuth file you just downloaded. Resume Builder validates it without saving a copy.</p>
      <input id="gmail-oauth-file" type="file" accept="application/json,.json" onChange={(event) => { setFile(event.target.files?.[0] || null); setAuthorizationUrl(""); setError(""); }} disabled={saving} />
      <button className="primary-button" onClick={() => void authorize()} disabled={!file || saving}>{saving ? "Preparing Google…" : "Use this file"}</button>
      {authorizationUrl && <div className="authorization-ready" role="status"><strong>Your file is valid.</strong><p>Continue to Google to grant read-only access. You’ll return here when it’s done.</p><a className="primary-button" href={authorizationUrl}>Continue to Google</a></div>}
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
    <div className="setup-navigation">
      <button className="text-button" onClick={() => move(step - 1)} disabled={step === 0}>Back</button>
      {step < setup.steps.length - 1 && <button className="primary-button" onClick={() => move(step + 1)}>Next step</button>}
    </div>
  </div>;
}

function TelegramSetup({ connected, onConnected }: { connected: boolean; onConnected: () => void }) {
  const [token, setToken] = useState("");
  const [pairing, setPairing] = useState<TelegramPairing | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!pairing || pairing.status !== "waiting") return;
    const timer = window.setInterval(() => {
      getTelegramPairing(pairing.session_id).then((result) => {
        setPairing(result);
        if (result.status === "connected") onConnected();
      }).catch((reason: unknown) => { setError(reason instanceof Error ? reason.message : "Could not check Telegram pairing."); window.clearInterval(timer); });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pairing?.session_id, pairing?.status, onConnected]);

  async function begin() {
    setSaving(true); setError("");
    try {
      const result = await startTelegramPairing(token.trim());
      setToken(""); setPairing(result);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not validate the Telegram bot.");
    } finally { setSaving(false); }
  }

  if (connected && !pairing) return <div className="integration-setup integration-connected-copy"><strong>Your private Telegram bot is ready.</strong><p>Messages are accepted only from the private account paired during setup.</p></div>;
  if (pairing?.status === "connected") return <div className="integration-setup integration-connected-copy" role="status"><strong>@{pairing.username} is connected.</strong><p>You can now message your private career assistant in Telegram.</p></div>;
  return <div className="integration-setup guided-integration telegram-setup">
    {!pairing || pairing.status === "failed" ? <>
      <div className="setup-step">
        <span className="setup-kicker">About 2 minutes</span>
        <h3>Create your private Telegram bot</h3>
        <ol><li>Open the official BotFather.</li><li>Send <strong>/newbot</strong> and follow its prompts.</li><li>Copy the bot token it gives you.</li></ol>
        <a className="secondary-button external-setup-link" href="https://t.me/BotFather" target="_blank" rel="noreferrer">Open BotFather ↗</a>
      </div>
      <form className="telegram-token-form" onSubmit={(event) => { event.preventDefault(); void begin(); }}>
        <label htmlFor="telegram-token">Bot token</label>
        <p>The token is sent only to your local Resume Builder server and is never shown again.</p>
        <input id="telegram-token" type="password" autoComplete="new-password" spellCheck={false} placeholder="Paste the token from BotFather" value={token} onChange={(event) => setToken(event.target.value)} disabled={saving} required />
        <button className="primary-button" disabled={saving || !token.trim()}>{saving ? "Checking bot…" : "Verify bot and pair"}</button>
      </form>
      {pairing?.error && <p className="error-text" role="alert">{pairing.error}</p>}
    </> : <div className="pairing-stage" aria-live="polite">
      <div><span className="setup-kicker">Bot verified</span><h3>Connect @{pairing.username}</h3><p>Scan this code with your phone or open Telegram, then tap <strong>Start</strong>. The pairing code expires after two minutes.</p><a className="primary-button" href={pairing.pairing_url} target="_blank" rel="noreferrer">Open Telegram</a></div>
      <img src={pairing.qr_url} alt={`QR code to pair @${pairing.username}`} />
      <p className="pairing-wait"><span />Waiting for you to tap Start…</p>
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
  </div>;
}

function UnavailableSetup({ name }: { name: string }) {
  return <div className="integration-setup integration-connected-copy"><strong>{name} can’t be configured from this page yet.</strong><p>This portal does not expose internal setup commands. Existing connections continue to work.</p></div>;
}

export function IntegrationsSection() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    const gmailResult = new URLSearchParams(window.location.search).get("gmail");
    if (gmailResult === "connected") setMessage("Gmail connected with read-only access.");
    if (gmailResult === "cancelled") setError("Google authorization was cancelled. Gmail remains unchanged.");
    if (gmailResult === "error") setError("Gmail could not be connected. Start the connection again.");
  }, []);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getIntegrations()
      .then((result) => { if (active) setIntegrations(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load integrations"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reloadKey]);

  function refresh() { setReloadKey((key) => key + 1); }

  return (
    <section className="integrations-page" aria-labelledby="integrations-heading">
      <h2 id="integrations-heading">Integrations</h2>
      <p className="page-intro">Connect AI, email, and notification services without leaving the portal.</p>
      {message && <p className="integration-banner success" role="status">{message}</p>}
      {error && <ErrorMessage message={error} retry={() => { setError(""); refresh(); }} />}
      {loading ? <LoadingRows /> : integrations.some((item) => item.id !== "job-providers") ? (
        <section className="integration-list">
          {integrations.filter((item) => item.id !== "job-providers").map((item) => (
            <article className="integration-row" key={item.id}>
              <button className="integration-summary" onClick={() => setOpenId(openId === item.id ? null : item.id)} aria-expanded={openId === item.id}>
                <span className={`integration-icon icon-${item.id}`}>{item.name.slice(0, 1)}</span>
                <span className="integration-copy"><strong>{item.name}</strong><small>{item.description}</small></span>
                <span className={`connection-state ${item.status}`}><i />{item.detail}</span>
                <span className="chevron" aria-hidden="true">⌄</span>
              </button>
              {openId === item.id && (item.id === "openrouter" ? <OpenRouterSetup connected={item.status === "connected"} onSaved={(savedMessage) => { setMessage(savedMessage); refresh(); }} /> : item.id === "gmail" ? <GmailSetup connected={item.status === "connected"} /> : item.id === "telegram" ? <TelegramSetup connected={item.status === "connected"} onConnected={refresh} /> : <UnavailableSetup name={item.name} />)}
            </article>
          ))}
        </section>
      ) : <EmptyState title="No integrations available">Integration options will appear here when available.</EmptyState>}
    </section>
  );
}
