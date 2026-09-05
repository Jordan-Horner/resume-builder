import { useEffect, useMemo, useState } from "react";
import { getApplications } from "../api";
import { EmptyState, ErrorMessage, LoadingRows, SearchIcon } from "../components";
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
      <section className="search-tools compact" aria-label="Application filters">
        <label className="search-field">
          <SearchIcon />
          <span className="sr-only">Search applications</span>
          <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search role or company" />
        </label>
        <select value={status} onChange={(event) => setStatus(event.target.value)} aria-label="Filter by application status">
          <option value="">All statuses</option>
          {statuses.map((item) => <option key={item} value={item}>{label(item)}</option>)}
        </select>
      </section>
      {error && <ErrorMessage message={error} retry={() => { setError(""); setReloadKey((key) => key + 1); }} />}
      {loading ? <LoadingRows /> : filtered.length ? (
        <section className="application-list">
          <div className="table-heading"><span>{filtered.length} applications</span><span>Latest status</span></div>
          {filtered.map((item) => (
            <article className="application-row" key={item.id}>
              <button className="application-summary" onClick={() => setOpenId(openId === item.id ? null : item.id)} aria-expanded={openId === item.id}>
                <span><strong>{item.role}</strong><small>{item.company} · Applied {item.applied_on}</small></span>
                <span className={`status status-${item.current_status}`}>{label(item.current_status)}</span>
              </button>
              {openId === item.id && (
                <div className="application-history">
                  <h3>History</h3>
                  {item.events.map((event) => (
                    <div className="history-event" key={event.id}>
                      <span className="timeline-dot" />
                      <div><strong>{label(event.status)}</strong><small>{event.effective_on}{event.stage ? ` · ${event.stage}` : ""}</small>{event.note && <p>{event.note}</p>}</div>
                    </div>
                  ))}
                  {item.application_url && <a href={item.application_url} target="_blank" rel="noreferrer">Open application page</a>}
                </div>
              )}
            </article>
          ))}
        </section>
      ) : <EmptyState title="No applications found">Applied jobs will appear here with their status history.</EmptyState>}
    </div>
  );
}
