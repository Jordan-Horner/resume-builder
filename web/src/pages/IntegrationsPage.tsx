import { useCallback, useEffect, useState } from "react";
import { getIntegrations } from "../api";
import { EmptyState, ErrorMessage, LoadingRows } from "../components";
import { GmailSetup } from "../integrations/GmailSetup";
import { BrightDataSetup } from "../integrations/BrightDataSetup";
import { OpenRouterSetup } from "../integrations/OpenRouterSetup";
import { TelegramSetup } from "../integrations/TelegramSetup";
import { UnavailableSetup } from "../integrations/UnavailableSetup";
import type { Integration } from "../types";

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

  const refresh = useCallback(() => setReloadKey((key) => key + 1), []);
  const visibleIntegrations = integrations.filter((item) => item.id !== "job-providers");

  return (
    <section className="integrations-page" aria-labelledby="integrations-heading">
      <h2 id="integrations-heading">Integrations</h2>
      <p className="page-intro">Connect AI, email, and notification services without leaving the portal.</p>
      {message && <p className="integration-banner success" role="status">{message}</p>}
      {error && <ErrorMessage message={error} retry={() => { setError(""); refresh(); }} />}
      {loading ? <LoadingRows label="Loading integrations" /> : visibleIntegrations.length ? (
        <section className="integration-list" aria-label="Available integrations">
          {visibleIntegrations.map((item) => {
            const open = openId === item.id;
            return <article className="integration-row" key={item.id}>
              <button className="integration-summary" onClick={() => setOpenId(open ? null : item.id)} aria-expanded={open} aria-controls={`integration-${item.id}`}>
                <span className={`integration-icon icon-${item.id}`} aria-hidden="true">{item.name.slice(0, 1)}</span>
                <span className="integration-copy"><strong>{item.name}</strong><small>{item.description}</small></span>
                <span className={`connection-state ${item.status}`}><i />{item.detail}</span>
                <span className="chevron" aria-hidden="true">⌄</span>
              </button>
              {open && <div id={`integration-${item.id}`}>
                {item.id === "openrouter" ? <OpenRouterSetup connected={item.status === "connected"} onSaved={(savedMessage) => { setMessage(savedMessage); refresh(); }} />
                  : item.id === "bright-data" ? <BrightDataSetup connected={item.status !== "not_connected"} initialEnabled={item.settings?.enabled ?? false} initialLimit={item.settings?.max_records_per_refresh ?? 100} onSaved={(savedMessage) => { setMessage(savedMessage); refresh(); }} />
                  : item.id === "gmail" ? <GmailSetup connected={item.status === "connected"} />
                    : item.id === "telegram" ? <TelegramSetup connected={item.status === "connected"} onConnected={refresh} />
                      : <UnavailableSetup name={item.name} />}
              </div>}
            </article>;
          })}
        </section>
      ) : <EmptyState title="No integrations available">Integration options will appear here when available.</EmptyState>}
    </section>
  );
}
