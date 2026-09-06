import { useState } from "react";
import { configureBrightData } from "../api";

export function BrightDataSetup({
  connected,
  initialEnabled,
  initialLimit,
  onSaved,
}: {
  connected: boolean;
  initialEnabled: boolean;
  initialLimit: number;
  onSaved: (message: string) => void;
}) {
  const [token, setToken] = useState("");
  const [enabled, setEnabled] = useState(initialEnabled);
  const [limit, setLimit] = useState(initialLimit);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState("");

  async function save() {
    setSaving(true); setError("");
    try {
      const result = await configureBrightData(token.trim(), enabled, limit);
      setToken(""); onSaved(result.message);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save Bright Data.");
    } finally { setSaving(false); }
  }

  return <form className="integration-setup bright-data-setup" onSubmit={(event) => { event.preventDefault(); void save(); }}>
    <label htmlFor="bright-data-token">{connected ? "Replace API token (optional)" : "Bright Data API token"}</label>
    <p>Runs only after free first-party matching. The token is stored privately on your server and never shown again.</p>
    <input id="bright-data-token" type="password" autoComplete="new-password" spellCheck={false} maxLength={512} placeholder={connected ? "Leave blank to keep the saved token" : "Paste your API token"} value={token} onChange={(event) => setToken(event.target.value)} disabled={saving} required={!connected} />
    <label className="source-toggle"><span>Enrich unresolved LinkedIn jobs</span><input type="checkbox" role="switch" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} disabled={saving} /></label>
    <label htmlFor="bright-data-limit">Maximum records per refresh</label>
    <input id="bright-data-limit" type="number" min={1} max={1000} value={limit} onChange={(event) => setLimit(Number(event.target.value))} disabled={saving} required />
    <div><button className="primary-button" disabled={saving || (!connected && !token.trim())}>{saving ? "Saving…" : "Save integration"}</button></div>
    <a href="https://brightdata.com/products/web-scraper/linkedin/jobs" target="_blank" rel="noreferrer">Get a Bright Data token ↗</a>
    {error && <p className="error-text" role="alert">{error}</p>}
  </form>;
}
