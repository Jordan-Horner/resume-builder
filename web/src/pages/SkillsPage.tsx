import { useEffect, useMemo, useState } from "react";
import { getSkills, setSkillSearch } from "../api";
import { EmptyState, ErrorMessage } from "../components";
import type { CareerSkill } from "../types";

export function SkillsPage() {
  const [skills, setSkills] = useState<CareerSkill[] | null>(null);
  const [query, setQuery] = useState("");
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const load = () => { setError(""); getSkills().then(setSkills).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load vault skills.")); };
  useEffect(load, []);
  const visible = useMemo(() => (skills || []).filter((item) => `${item.title} ${item.description} ${item.themes.join(" ")}`.toLocaleLowerCase().includes(query.toLocaleLowerCase().trim())), [skills, query]);
  async function toggle(skill: CareerSkill) {
    if (busy) return;
    setBusy(skill.id); setError("");
    try {
      const updated = await setSkillSearch(skill.id, !skill.search.enabled);
      setSkills((current) => current?.map((item) => item.id === updated.id ? updated : item) || current);
    } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not update search signals."); }
    finally { setBusy(""); }
  }
  if (error && !skills) return <section className="page"><ErrorMessage message={error} retry={load} /></section>;
  if (!skills) return <section className="page" role="status">Loading vault skills…</section>;
  return <section className="page career-page">
    <header className="career-heading"><div><p className="eyebrow">Career evidence</p><h1>Skills</h1><p className="page-intro">Confirmed skills come directly from your vault. Select a small set to broaden future job searches.</p></div><div className="career-count"><strong>{skills.length}</strong><span>vault skills</span></div></header>
    {!skills.length ? <EmptyState title="No confirmed skills yet">Importing a resume preserves source evidence. Skills appear here after that evidence is reviewed and added to the vault.</EmptyState> : <>
      <div className="career-tools"><label className="search-field"><span className="sr-only">Search skills</span><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="m16 16 5 5"/></svg><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search skills and evidence" /></label><p>{skills.filter((item) => item.search.enabled).length} search signals selected</p></div>
      {error && <ErrorMessage message={error} retry={load} />}
      <div className="career-list" role="list">{visible.map((skill) => <article className="career-row skill-library-row" role="listitem" key={skill.id}>
        <div className="career-row-main"><div className="career-row-title"><h3>{skill.title}</h3><span className={`evidence-state ${skill.status_tone}`}>{skill.status_label}</span></div><p>{skill.description}</p><small>{skill.resumes.length ? `Used by ${skill.resumes.length} resume${skill.resumes.length === 1 ? "" : "s"}` : "Not currently used in a resume"}{skill.themes.length ? ` · ${skill.themes.join(" · ")}` : ""}</small>{skill.search.disabled_reason && <small>{skill.search.disabled_reason}</small>}</div>
        <label className="source-toggle skill-search-toggle"><span>{skill.search.enabled ? "Search on" : "Search off"}</span><input type="checkbox" checked={skill.search.enabled} disabled={busy === skill.id || !skill.search.can_change} onChange={() => void toggle(skill)} aria-label={`Use ${skill.title} in job search`} /></label>
      </article>)}</div>
      {!visible.length && <p className="career-no-results">No vault skills match “{query}”.</p>}
    </>}
  </section>;
}
