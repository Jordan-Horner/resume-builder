import { useEffect, useState } from "react";
import { getTelegramPairing, startTelegramPairing } from "../api";
import type { TelegramPairing } from "../types";

export function TelegramSetup({ connected, onConnected }: { connected: boolean; onConnected: () => void }) {
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
      }).catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Could not check Telegram pairing.");
        window.clearInterval(timer);
      });
    }, 2000);
    return () => window.clearInterval(timer);
  }, [pairing?.session_id, pairing?.status, onConnected]);

  async function begin() {
    setSaving(true); setError("");
    try { setToken(""); setPairing(await startTelegramPairing(token.trim())); }
    catch (reason) { setError(reason instanceof Error ? reason.message : "Could not validate the Telegram bot."); }
    finally { setSaving(false); }
  }

  if (connected && !pairing) return <div className="integration-setup integration-connected-copy"><strong>Your private Telegram bot is ready.</strong><p>Messages are accepted only from the private account paired during setup.</p></div>;
  if (pairing?.status === "connected") return <div className="integration-setup integration-connected-copy" role="status"><strong>@{pairing.username} is connected.</strong><p>You can now message your private career assistant in Telegram.</p></div>;
  return <div className="integration-setup guided-integration telegram-setup">
    {!pairing || pairing.status === "failed" ? <>
      <div className="setup-step"><span className="setup-kicker">About 2 minutes</span><h3>Create your private Telegram bot</h3><ol><li>Open the official BotFather.</li><li>Send <strong>/newbot</strong> and follow its prompts.</li><li>Copy the bot token it gives you.</li></ol><a className="secondary-button external-setup-link" href="https://t.me/BotFather" target="_blank" rel="noreferrer">Open BotFather ↗</a></div>
      <form className="telegram-token-form" onSubmit={(event) => { event.preventDefault(); void begin(); }}>
        <label htmlFor="telegram-token">Bot token</label><p>The token is sent only to your local Resume Builder server and is never shown again.</p>
        <input id="telegram-token" type="password" autoComplete="new-password" spellCheck={false} placeholder="Paste the token from BotFather" value={token} onChange={(event) => setToken(event.target.value)} disabled={saving} required />
        <button className="primary-button" disabled={saving || !token.trim()}>{saving ? "Checking bot…" : "Verify bot and pair"}</button>
      </form>
      {pairing?.error && <p className="error-text" role="alert">{pairing.error}</p>}
    </> : <div className="pairing-stage" aria-live="polite">
      <div><span className="setup-kicker">Bot verified</span><h3>Connect @{pairing.username}</h3><p>Scan this code with your phone or open Telegram, then tap <strong>Start</strong>. The pairing code expires after two minutes.</p><a className="primary-button" href={pairing.pairing_url} target="_blank" rel="noreferrer">Open Telegram</a></div>
      <img src={pairing.qr_url} alt={`QR code to pair @${pairing.username}`} /><p className="pairing-wait"><span />Waiting for you to tap Start…</p>
    </div>}
    {error && <p className="error-text" role="alert">{error}</p>}
  </div>;
}
