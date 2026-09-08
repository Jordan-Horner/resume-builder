import { useEffect, useMemo, useState } from "react";
import { getApplications, markApplicationReapplied } from "../api";
import { EmptyState, ErrorMessage, LoadingRows, SearchField } from "../components";
import type { Application } from "../types";

function label(value: string) {
  return value.split("_").map((part) => part[0].toUpperCase() + part.slice(1)).join(" ");
}

export function ApplicationsPage() {
  const [applications, setApplications] = useState<Application[]>([]);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState("");
  const [openId, setOpenId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [savingId, setSavingId] = useState<string | null>(null);
  const [reloadKey, setReloadKey] = useState(0);

  useEffect(() => {
    setLoading(true);
    getApplications()
      .then(setApplications)
      .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load applications"))
      .finally(() => setLoading(false));
  }, [reloadKey]);

  const statuses = useMemo(() => [...new Set(applications.map((item) => item.current_status))].sort(), [applications]);
  const filtered = applications.filter((item) => {
    const matchesSearch = `${item.role} ${item.company}`.toLowerCase().includes(search.toLowerCase());
    return matchesSearch && (!status || item.current_status === status);
  });

  return (
    <div className="page applications-page">
      <section className="page-heading">
        <div>
          <p className="eyebrow">Your search history</p>
          <h1>Applications</h1>
          <p className="page-intro">Every role you’ve applied for, with its latest status and history.</p>
        </div>
      </section>
      {notice && <p className="action-notice" role="status">{notice}</p>}
      <section className="search-tools compact" aria-label="Application filters">
        <SearchField label="Search applications" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search role or company" />
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by application status">
          <option value="">All statuses</option>
          {statuses.map((item) => <option key={item} value={item}>{label(item)}</option>)}
        </select>
      </section>
      {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
      {loading ? <LoadingRows label="Loading applications" /> : filtered.length ? (
        <section className="application-list">
          <div className="table-heading"><span>{filtered.length} applications</span><span>Latest status</span></div>
          {filtered.map((item) => (
            <article className="application-row" key={item.id}>
              <button className="application-summary" onClick={() => setOpenId(openId === item.id ? null : item.id)} aria-expanded={openId === item.id}>
                <span><strong>{item.role}</strong><small>{item.company} · Applied {item.applied_on}</small></span>
                <span className="application-statuses">
                  {item.reapplication && <span className="reopened-pill">{item.reapplication.kind === "reopened" ? "Reopened" : "Possible repost"}</span>}
                  <span className={`status status-${item.current_status}`}>{label(item.current_status)}</span>
                </span>
              </button>
              {openId === item.id && (
                <div className="application-history">
                  <div className="application-resume">
                    <span>Resume used</span>
                    {item.resume ? <strong>{item.resume.preview_url ? <a href={item.resume.preview_url} target="_blank" rel="noreferrer">{item.resume.name}</a> : item.resume.name}<small>{item.resume.detail}</small></strong> : <strong>Not recorded<small>This application predates resume tracking.</small></strong>}
                  </div>
                  <h3>History</h3>
                  {item.events.map((event) => (
                    <div className="history-event" key={event.id}>
                      <span className="timeline-dot" />
                      <div><strong>{label(event.status)}</strong><small>{event.effective_on}{event.stage ? ` · ${event.stage}` : ""}</small>{event.note && <p>{event.note}</p>}</div>
                    </div>
                  ))}
                  {item.application_url && <a href={item.application_url} target="_blank" rel="noreferrer">Open application page</a>}
                  {item.reapplication && (
                    <div className="reapplication-actions">
                      <p><strong>{item.reapplication.kind === "reopened" ? "This posting reopened." : "This may be a new hiring cycle."}</strong> {item.reapplication.reason}</p>
                      <a href={item.reapplication.url} target="_blank" rel="noreferrer">Review posting</a>
                      <button className="primary-button" type="button" disabled={savingId === item.id} onClick={() => {
                        setSavingId(item.id);
                        setError("");
                        markApplicationReapplied(item.id)
                          .then(() => {
                            setNotice(`${item.role} was recorded as a new application.`);
                            setReloadKey((key) => key + 1);
                          })
                          .catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not record the new application"))
                          .finally(() => setSavingId(null));
                      }}>{savingId === item.id ? "Saving…" : "I applied again"}</button>
                    </div>
                  )}
                </div>
              )}
            </article>
          ))}
        </section>
      ) : <EmptyState title="No applications found">Applied jobs will appear here with their status history.</EmptyState>}
    </div>
  );
}
