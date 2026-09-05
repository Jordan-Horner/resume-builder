import { useEffect, useRef, useState } from "react";
import { getSearchPreferences, saveSearchPreferences } from "../api";
import { ErrorMessage } from "../components";
import type { SearchPreferences, WorkMode } from "../types";

const roleKey = (value: string) => value.trim().replace(/\s+/g, " ").toLocaleLowerCase();
const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);

export function SearchPreferencesSection() {
  const [preferences, setPreferences] = useState<SearchPreferences | null>(null);
  const [title, setTitle] = useState("");
  const [locations, setLocations] = useState("");
  const [remoteTerms, setRemoteTerms] = useState("");
  const [removed, setRemoved] = useState<{ title: string; index: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [retry, setRetry] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  useEffect(() => {
    let active = true;
    setError("");
    getSearchPreferences().then((result) => {
      if (!active) return;
      setPreferences(result);
      setLocations(result.onsite_locations.join(", "));
      setRemoteTerms(result.remote_location_terms.join(", "));
    }).catch((reason: unknown) => {
      if (active) setError(reason instanceof Error ? reason.message : "Could not load search preferences.");
    });
    return () => { active = false; };
  }, [retry]);

  function patch(changes: Partial<SearchPreferences>) {
    setPreferences((current) => current ? { ...current, ...changes } : current);
    setNotice("");
  }

  function addTitle() {
    if (!preferences) return;
    const cleaned = title.trim().replace(/\s+/g, " ");
    if (cleaned.length < 2) { setNotice("Enter a complete job title."); return; }
    if (preferences.titles.some((item) => roleKey(item) === roleKey(cleaned))) {
      setNotice("That title is already included."); setTitle(""); return;
    }
    if (preferences.titles.length >= 22) { setNotice("Remove a title before adding another."); return; }
    patch({ titles: [...preferences.titles, cleaned] });
    setTitle(""); setNotice(`${cleaned} added.`); input.current?.focus();
  }

  function toggleMode(mode: WorkMode) {
    if (!preferences) return;
    const next = preferences.work_modes.includes(mode)
      ? preferences.work_modes.filter((item) => item !== mode)
      : [...preferences.work_modes, mode];
    patch({ work_modes: next });
  }

  async function save() {
    if (!preferences || busy) return;
    setBusy(true); setError(""); setNotice("");
    try {
      const updated = await saveSearchPreferences({
        ...preferences,
        onsite_locations: split(locations),
        remote_location_terms: split(remoteTerms),
      });
      setPreferences(updated);
      setLocations(updated.onsite_locations.join(", "));
      setRemoteTerms(updated.remote_location_terms.join(", "));
      setNotice("Search preferences saved. Future scrapes will use these titles.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not save search preferences.");
    } finally { setBusy(false); }
  }

  if (!preferences && error) return <ErrorMessage message={error} retry={() => setRetry((value) => value + 1)} />;
  if (!preferences) return <p role="status">Loading search preferences…</p>;
  const needsPlace = preferences.work_modes.includes("hybrid") || preferences.work_modes.includes("onsite");
  const pay = preferences.compensation;
  const valid = preferences.titles.length > 0 && preferences.work_modes.length > 0 && preferences.country.trim().length >= 2 && (!needsPlace || split(locations).length > 0) && (pay.skipped || pay.minimum !== null || pay.target !== null);

  return <section className="search-preferences-panel" aria-labelledby="search-preferences-heading">
    <div className="settings-section-heading"><div><h2 id="search-preferences-heading">Search preferences</h2><p>These settings shape every future scrape. Saving does not start one.</p></div><button className="primary-button" disabled={!valid || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save changes"}</button></div>

    <div className="settings-group"><div className="settings-group-copy"><h3>Job titles</h3><p>Every title below is searched. Add close alternatives you would genuinely consider.</p></div><div>
      <ul className="role-bubbles compact" aria-label="Titles included in searches">{preferences.titles.map((item, index) => <li className="role-bubble" key={roleKey(item)}><span>{item}</span><button type="button" aria-label={`Remove ${item}`} onClick={() => { patch({ titles: preferences.titles.filter((_, position) => position !== index) }); setRemoved({ title: item, index }); setNotice(`${item} removed.`); }}>×</button></li>)}</ul>
      {!preferences.titles.length && <p className="field-hint error-text">Add at least one title.</p>}
      <div className="role-feedback"><span role="status">{notice}</span>{removed && <button className="text-button" onClick={() => { const next = [...preferences.titles]; next.splice(Math.min(removed.index, next.length), 0, removed.title); patch({ titles: next }); setRemoved(null); setNotice(`${removed.title} restored.`); }}>Undo</button>}</div>
      <form className="role-add compact" onSubmit={(event) => { event.preventDefault(); addTitle(); }}><label className="field"><span>Add another title</span><div><input ref={input} value={title} maxLength={150} placeholder="e.g. Site Reliability Engineer" onChange={(event) => setTitle(event.target.value)} /><button className="secondary-button" disabled={!title.trim()} type="submit">Add</button></div></label></form>
    </div></div>

    <div className="settings-group"><div className="settings-group-copy"><h3>Where you can work</h3><p>Country scopes the scrape. Cities and regions apply only to hybrid and on-site roles.</p></div><div className="preference-fields"><label className="field"><span>Country</span><input value={preferences.country} maxLength={100} onChange={(event) => patch({ country: event.target.value })} /></label><div><span className="field-label">Work modes</span><div className="mode-grid compact">{(["remote", "hybrid", "onsite"] as WorkMode[]).map((mode) => <button type="button" key={mode} className={preferences.work_modes.includes(mode) ? "mode-card selected" : "mode-card"} aria-pressed={preferences.work_modes.includes(mode)} onClick={() => toggleMode(mode)}><span>{preferences.work_modes.includes(mode) ? "✓" : ""}</span><strong>{mode === "onsite" ? "On-site" : mode[0].toUpperCase() + mode.slice(1)}</strong></button>)}</div></div>{needsPlace && <label className="field"><span>Accepted cities or regions</span><input value={locations} placeholder="New York, Boston" onChange={(event) => setLocations(event.target.value)} /></label>}<label className="field"><span>Remote location terms <em>optional</em></span><input value={remoteTerms} placeholder="USA, East Coast" onChange={(event) => setRemoteTerms(event.target.value)} /></label></div></div>

    <div className="settings-group"><div className="settings-group-copy"><h3>Compensation</h3><p>Minimum filters poor fits. Target helps rank better-paying matches; it is not a ceiling. Jobs without pay stay visible.</p></div><div className="preference-fields"><label className="check-row compact"><input type="checkbox" checked={pay.skipped} onChange={(event) => patch({ compensation: { ...pay, skipped: event.target.checked, minimum: event.target.checked ? null : pay.minimum, target: event.target.checked ? null : pay.target, currency: event.target.checked ? null : (pay.currency || "USD"), period: event.target.checked ? null : (pay.period || "year") } })} /><span><strong>Don’t use compensation as a preference</strong></span></label>{!pay.skipped && <div className="form-grid"><label className="field"><span>Minimum</span><input type="number" min="0" value={pay.minimum ?? ""} onChange={(event) => patch({ compensation: { ...pay, minimum: event.target.value ? Number(event.target.value) : null } })} /></label><label className="field"><span>Target</span><input type="number" min="0" value={pay.target ?? ""} onChange={(event) => patch({ compensation: { ...pay, target: event.target.value ? Number(event.target.value) : null } })} /></label><label className="field"><span>Currency</span><select value={pay.currency || "USD"} onChange={(event) => patch({ compensation: { ...pay, currency: event.target.value } })}><option>USD</option><option>CAD</option><option>EUR</option><option>GBP</option></select></label><label className="field"><span>Period</span><select value={pay.period || "year"} onChange={(event) => patch({ compensation: { ...pay, period: event.target.value as "hour" | "year" } })}><option value="year">Per year</option><option value="hour">Per hour</option></select></label></div>}</div></div>
    {error && <ErrorMessage message={error} retry={() => void save()} />}
    <div className="settings-save-row"><button className="primary-button" disabled={!valid || busy} onClick={() => void save()}>{busy ? "Saving…" : "Save changes"}</button></div>
  </section>;
}
