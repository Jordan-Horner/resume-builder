import { useEffect, useState } from "react";
import { getIntegrations } from "../api";
import { EmptyState, ErrorMessage, LoadingRows } from "../components";
import type { Integration } from "../types";

export function IntegrationsSection() {
  const [integrations, setIntegrations] = useState<Integration[]>([]);
  const [openId, setOpenId] = useState<string | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getIntegrations()
      .then((result) => { if (active) setIntegrations(result); })
      .catch((reason: unknown) => { if (active) setError(reason instanceof Error ? reason.message : "Could not load integrations"); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [reloadKey]);

  async function copyCommand(integration: Integration) {
    try {
      await navigator.clipboard.writeText(integration.setup_command);
      setCopied(integration.id);
      window.setTimeout(() => setCopied(null), 1800);
    } catch {
      setError("Could not copy the setup command. Select it and copy it manually.");
    }
  }

  return (
    <section className="integrations-page" aria-labelledby="integrations-heading">
      <h2 id="integrations-heading">Integrations</h2>
      <p className="page-intro">Connect AI, email, and notification services.</p>
      {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
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
              {openId === item.id && (
                <div className="integration-setup">
                  <div><p>Run this setup from the Resume Builder project:</p><code>{item.setup_command}</code></div>
                  <button className="secondary-button" onClick={() => copyCommand(item)}>{copied === item.id ? "Copied" : "Copy setup command"}</button>
                </div>
              )}
            </article>
          ))}
        </section>
      ) : <EmptyState title="No integrations available">Integration options will appear here when configured.</EmptyState>}
    </section>
  );
}
