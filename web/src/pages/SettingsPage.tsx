import { useEffect, useState } from "react";
import { getBlockedCompanies, setCompanyBlocked } from "../api";
import { IntegrationsSection } from "./IntegrationsPage";
import { JobSources } from "./JobSources";
import { SETTINGS_SECTIONS, SETTINGS_SECTION_KEY, resolveSettingsSection } from "../settingsNavigation";

export function SettingsPage() {
  const [section] = useState(() => {
    let previous = null;
    try { previous = localStorage.getItem(SETTINGS_SECTION_KEY); }
    catch (error) { console.warn("Could not restore Settings section", error); }
    return resolveSettingsSection(window.location.pathname, previous);
  });
  useEffect(() => {
    window.history.replaceState({}, "", `/settings/${section}`);
    try { localStorage.setItem(SETTINGS_SECTION_KEY, section); }
    catch (error) { console.warn("Could not remember Settings section", error); }
  }, [section]);
  return <div className="page settings-page">
    <h1>Settings</h1>
    <div className="settings-layout">
    <nav className="settings-navigation" aria-label="Settings sections">
      {SETTINGS_SECTIONS.map((item) => <a key={item.id} className={section === item.id ? "nav-link active" : "nav-link"} aria-current={section === item.id ? "page" : undefined} href={`/settings/${item.id}`}>{item.label}</a>)}
    </nav>
    <label className="settings-mobile-navigation">Settings section<select value={section} onChange={(event) => window.location.assign(`/settings/${event.target.value}`)}>{SETTINGS_SECTIONS.map((item) => <option key={item.id} value={item.id}>{item.label}</option>)}</select></label>
    <div className="settings-content">
      {section === "scrapers" && <JobSources />}
      {section === "integrations" && <IntegrationsSection />}
      {section === "blocked-companies" && <BlockedCompaniesSection />}
    </div>
    </div>
  </div>;
}

function BlockedCompaniesSection() {
  const [companies, setCompanies] = useState<string[]>([]);
  const [search, setSearch] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    getBlockedCompanies().then((result) => {
      if (active) setCompanies(result.companies);
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load blocked companies.");
    }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [retry]);

  async function unblock(company: string) {
    setBusy(true);
    setError("");
    try {
      const result = await setCompanyBlocked(company, false);
      setCompanies(result.companies);
      setNotice(`${company} unblocked. Its jobs can appear again when they match your filters.`);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not unblock company. Try again.");
    } finally { setBusy(false); }
  }

  const visible = companies.filter((company) => company.toLowerCase().includes(search.trim().toLowerCase()));
  return <section className="blocked-company-panel" aria-labelledby="blocked-companies-heading">
    <h2 id="blocked-companies-heading">Blocked companies</h2>
    <p>Jobs from these companies are hidden from your review queue. Your application history stays unchanged.</p>
    {loading ? <p role="status">Loading blocked companies…</p> : <>
      {companies.length > 0 && <label className="field"><span>Find a blocked company</span><input value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search companies" /></label>}
      {!companies.length && !error && <p>No blocked companies. You can block a company from any job’s details.</p>}
      <ul className="role-bubbles">{visible.map((company) => <li className="role-bubble" key={company}><span>{company}</span><button disabled={busy} aria-label={`Unblock ${company}`} onClick={() => void unblock(company)}>×</button></li>)}</ul>
      {companies.length > 0 && !visible.length && <p>No matching blocked companies.</p>}
    </>}
    {error && <p role="alert">{error} <button className="text-button" onClick={() => { setError(""); setRetry((value) => value + 1); }}>Retry</button></p>}
    {notice && <p role="status">{notice}</p>}
  </section>;
}
