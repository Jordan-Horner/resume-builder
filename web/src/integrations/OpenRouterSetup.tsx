import { useState } from "react";
import { configureOpenRouter } from "../api";

export function OpenRouterSetup({ connected, onSaved }: { connected: boolean; onSaved: (message: string) => void }) {
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
