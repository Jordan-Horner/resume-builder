import { useRef, useState, type ReactNode } from "react";
import { answerOnboarding, backOnboarding, getOnboardingStatus, skipOnboarding, startOnboarding, uploadResume } from "../api";
import type { OnboardingSetup, OnboardingStatus, WorkMode } from "../types";

interface PageProps { initial: OnboardingStatus; onComplete: () => void }
interface StepProps { setup: OnboardingSetup; busy: boolean; error: string; onSubmit: (answer: Record<string, unknown>) => void; onBack: () => void }
const LABELS = ["Resume", "Roles", "Location", "Pay", "Review"];

function Progress({ status }: { status: OnboardingStatus }) {
  return <div className="onboarding-progress" aria-label={`Step ${status.progress} of 5`}>
    {LABELS.map((label, index) => <span key={label} className={index < status.progress ? "complete" : ""} />)}
    <small>Step {status.progress} of 5 · {LABELS[status.progress - 1]}</small>
  </div>;
}

function ResumeStep({ busy, error, done }: { busy: boolean; error: string; done: () => void }) {
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  async function submit() { if (file) { await uploadResume(file); done(); } }
  return <div className="onboarding-content">
    <p className="eyebrow">Your starting point</p><h1 id="onboarding-title">Add your resume</h1>
    <p className="onboarding-lede">We’ll use it to suggest roles. You review every choice before job search is configured.</p>
    <div className={dragging ? "resume-dropzone dragging" : "resume-dropzone"} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); setFile(event.dataTransfer.files[0] || null); }}>
      <span className="file-glyph" aria-hidden="true">↥</span><strong>{file?.name || "Drop your resume here"}</strong>
      <span>{file ? `${Math.max(1, Math.round(file.size / 1024))} KB selected` : "PDF, DOCX, Markdown, HTML, or text · up to 10 MB"}</span>
      <input ref={input} type="file" accept=".pdf,.docx,.md,.txt,.html,.htm,.tex" onChange={(event) => setFile(event.target.files?.[0] || null)} />
      <button className="secondary-button" onClick={() => input.current?.click()}>{file ? "Choose another" : "Choose a file"}</button>
    </div>
    {error && <p className="onboarding-error" role="alert">{error}</p>}
    <div className="onboarding-footer"><p>Your resume stays in this private workspace.</p><button className="onboarding-primary" onClick={submit} disabled={!file || busy}>{busy ? "Adding…" : "Add resume"}</button></div>
  </div>;
}

function AiChoice({ status, busy, error, choose }: { status: OnboardingStatus; busy: boolean; error: string; choose: (ai: boolean, key?: string) => void }) {
  const [showKey, setShowKey] = useState(false);
  const [key, setKey] = useState("");
  return <div className="onboarding-content">
    <p className="eyebrow">Resume ready</p><h1 id="onboarding-title">How should we suggest roles?</h1>
    <p className="onboarding-lede">OpenRouter can find adjacent roles from the meaning of your experience. It does not change how jobs are scraped.</p>
    <div className="choice-stack">
      <div className="choice-card recommended"><div><span className="choice-kicker">Recommended</span><strong>Use OpenRouter suggestions</strong><p>Get richer role and search direction suggestions from your resume.</p></div>{status.openrouter_configured ? <button className="secondary-button" onClick={() => choose(true)} disabled={busy}>{busy ? "Generating roles…" : "Use OpenRouter"}</button> : <button className="secondary-button" onClick={() => setShowKey(true)}>Connect</button>}</div>
      {showKey && <div className="key-entry"><label htmlFor="openrouter-key">OpenRouter API key</label><div><input id="openrouter-key" type="password" value={key} onChange={(event) => setKey(event.target.value)} placeholder="sk-or-v1-…" autoComplete="off" /><button className="onboarding-primary" onClick={() => choose(true, key)} disabled={!key.trim() || busy}>{busy ? "Generating…" : "Generate roles"}</button></div><small>Stored only in this private workspace. Your resume is sent to OpenRouter for this suggestion step.</small></div>}
      <button className="choice-card choice-button" onClick={() => choose(false)} disabled={busy}><div><strong>Enter roles manually</strong><p>Start with titles found directly in your resume and edit them yourself.</p></div><span>→</span></button>
    </div>{error && <p className="onboarding-error" role="alert">{error}</p>}
  </div>;
}

const roleKey = (title: string) => title.trim().replace(/\s+/g, " ").toLocaleLowerCase();
function RolesStep({ setup, busy, error, onSubmit, onBack }: StepProps) {
  const storageKey = `onboarding-roles-v1:${setup.session_id}`;
  const [draft] = useState(() => {
    try {
      const raw = localStorage.getItem(storageKey);
      if (!raw) return { titles: setup.roles.filter((role) => role.intent !== "dont_seed").map((role) => role.title), input: "", error: "" };
      const saved = JSON.parse(raw);
      if (!Array.isArray(saved.titles) || !saved.titles.every((title: unknown) => typeof title === "string") || typeof saved.input !== "string") throw new Error("Invalid saved roles");
      return { titles: saved.titles as string[], input: saved.input as string, error: "" };
    } catch {
      return { titles: setup.roles.filter((role) => role.intent !== "dont_seed").map((role) => role.title), input: "", error: "Could not restore your browser draft. Your last submitted roles are shown." };
    }
  });
  const [titles, setTitles] = useState<string[]>(draft.titles);
  const [add, setAdd] = useState(draft.input);
  const [saveError, setSaveError] = useState(draft.error);
  const [notice, setNotice] = useState("");
  const [highlight, setHighlight] = useState("");
  const [removed, setRemoved] = useState<{ title: string; index: number } | null>(null);
  const input = useRef<HTMLInputElement>(null);
  function persist(next: string[], text: string) {
    try { localStorage.setItem(storageKey, JSON.stringify({ titles: next, input: text })); setSaveError(""); }
    catch { setSaveError("Could not save in this browser. Retry, or Continue to save your roles to setup."); }
  }
  function update(next: string[], text = add) { setTitles(next); setAdd(text); persist(next, text); }
  function addRole(): string[] | null {
    const title = add.trim().replace(/\s+/g, " ");
    if (!title) return titles;
    if (title.length < 2) { setNotice("Use at least two characters for a job title."); input.current?.focus(); return null; }
    const existing = titles.find((item) => roleKey(item) === roleKey(title));
    if (existing) { setHighlight(roleKey(existing)); setNotice("Already added."); update(titles, ""); input.current?.focus(); return titles; }
    if (titles.length >= 22) { setNotice("You can include up to 22 roles. Remove one before adding another."); return null; }
    const next = [...titles, title];
    update(next, ""); setHighlight(roleKey(title)); setNotice(`${title} added.`); input.current?.focus();
    return next;
  }
  function submit() {
    const next = addRole();
    if (!next?.length) return;
    const included = new Set(next.map(roleKey));
    onSubmit({
      decisions: Object.fromEntries(setup.roles.map((role) => [role.role_id, included.has(roleKey(role.title)) ? "search" : "dont_seed"])),
      add: next.filter((title) => !setup.roles.some((role) => roleKey(role.title) === roleKey(title))),
    });
  }
  return <div className="onboarding-content roles-step role-bubbles-step">
    <p className="eyebrow">Your next role</p>
    <h1 id="onboarding-title">Which roles do you want to search for?</h1>
    <p className="onboarding-lede">We suggested these from your resume. Keep the ones you want, remove the rest, or add your own.</p>
    <ul className="role-bubbles" aria-label="Roles included in your job search">{titles.map((title, index) =>
      <li key={roleKey(title)} className={highlight === roleKey(title) ? "role-bubble highlighted" : "role-bubble"}>
        <span>{title}</span><button type="button" disabled={busy} aria-label={`Remove ${title}`} onClick={() => {
          update(titles.filter((_, position) => position !== index)); setRemoved({ title, index }); setHighlight(""); setNotice(`${title} removed.`);
        }}>×</button>
      </li>
    )}</ul>
    {!titles.length && <p className="role-empty">Add at least one role to find jobs.</p>}
    <div className="role-feedback"><span role="status">{notice}</span>{removed && <button className="text-button" type="button" disabled={busy} onClick={() => {
      if (!titles.some((title) => roleKey(title) === roleKey(removed.title)) && titles.length < 22) {
        const next = [...titles]; next.splice(removed.index, 0, removed.title); update(next);
        setNotice(`${removed.title} restored.`); setHighlight(roleKey(removed.title)); setRemoved(null);
      } else { setNotice("Role is already included, or the 22-role limit has been reached."); }
    }}>Undo removal</button>}</div>
    <form className="role-add" onSubmit={(event) => { event.preventDefault(); addRole(); }}>
      <label className="field" htmlFor="new-role"><span>Add a job title</span></label>
      <div><input ref={input} id="new-role" value={add} maxLength={160} placeholder="e.g. Platform Engineer" disabled={busy} onChange={(event) => { setAdd(event.target.value); persist(titles, event.target.value); }} /><button className="secondary-button" type="submit" disabled={busy || !add.trim()}>Add</button></div>
    </form>
    <div className="role-draft-status">{saveError ? <p role="alert">{saveError} <button className="text-button" onClick={() => persist(titles, add)}>Retry</button></p> : <small>Draft saved in this browser</small>}</div>
    <Actions busy={busy} error={error} onBack={onBack} disabled={!titles.length && !add.trim()} onContinue={submit} />
  </div>;
}

function Actions({ busy, error, onBack, onContinue, disabled = false, label = "Continue" }: { busy: boolean; error: string; onBack: () => void; onContinue: () => void; disabled?: boolean; label?: string }) {
  return <>{error && <p className="onboarding-error" role="alert">{error}</p>}<div className="onboarding-footer"><button className="onboarding-back" onClick={onBack}>Back</button><button className="onboarding-primary" disabled={busy || disabled} onClick={onContinue}>{busy ? "Saving…" : label}</button></div></>;
}
function Shell({ eyebrow, title, lede, children, ...actions }: { eyebrow: string; title: string; lede: string; children: ReactNode } & Parameters<typeof Actions>[0]) {
  return <div className="onboarding-content"><p className="eyebrow">{eyebrow}</p><h1 id="onboarding-title">{title}</h1><p className="onboarding-lede">{lede}</p>{children}<Actions {...actions} /></div>;
}
const split = (value: string) => value.split(",").map((item) => item.trim()).filter(Boolean);
function LocationStep({ setup, busy, error, onSubmit, onBack }: StepProps) {
  const old = setup.location;
  const [country, setCountry] = useState(setup.eligibility?.intended_country || "United States");
  const [modes, setModes] = useState<WorkMode[]>(old?.accepted_work_modes || ["remote"]);
  const [locations, setLocations] = useState(old?.accepted_onsite_locations.join(", ") || "");
  const [remote, setRemote] = useState(old?.remote_location_terms?.join(", ") || "");
  const needsPlace = modes.includes("hybrid") || modes.includes("onsite");
  function toggle(mode: WorkMode) { setModes(modes.includes(mode) ? modes.filter((item) => item !== mode) : [...modes, mode]); }
  return <Shell eyebrow="Location & work mode" title="Where do you want to work?" lede="Choose where to search and the work arrangements you want." busy={busy} error={error} onBack={onBack} disabled={country.trim().length < 2 || !modes.length || (needsPlace && !locations.trim())} onContinue={() => onSubmit({ search_country: country.trim(), accepted_work_modes: modes, accepted_onsite_locations: split(locations), remote_location_terms: split(remote).length ? split(remote) : null })}>
    <label className="field"><span>Search country</span><input value={country} onChange={(event) => setCountry(event.target.value)} maxLength={100} /><small>Used as the location for job searches.</small></label>
    <div className="mode-grid">{(["remote", "hybrid", "onsite"] as WorkMode[]).map((mode) => <button key={mode} className={modes.includes(mode) ? "mode-card selected" : "mode-card"} aria-pressed={modes.includes(mode)} onClick={() => toggle(mode)}><span>{modes.includes(mode) ? "✓" : ""}</span><strong>{mode === "onsite" ? "On-site" : `${mode[0].toUpperCase()}${mode.slice(1)}`}</strong></button>)}</div>
    <div className="form-grid single">{needsPlace && <label className="field"><span>Acceptable cities or regions</span><input value={locations} onChange={(event) => setLocations(event.target.value)} placeholder="New York, Boston" /></label>}
    <label className="field"><span>Remote location terms (optional)</span><input value={remote} onChange={(event) => setRemote(event.target.value)} placeholder="US, East Coast" /></label></div>
  </Shell>;
}
function CompensationStep({ setup, busy, error, onSubmit, onBack }: StepProps) {
  const old = setup.compensation; const [skip, setSkip] = useState(old?.skipped ?? false); const [minimum, setMinimum] = useState(old?.minimum?.toString() || ""); const [target, setTarget] = useState(old?.target?.toString() || ""); const [currency, setCurrency] = useState(old?.currency || "USD"); const [period, setPeriod] = useState(old?.period || "year");
  return <Shell eyebrow="Compensation" title="Set a pay preference" lede="Optional. Jobs without listed pay will still remain visible." busy={busy} error={error} onBack={onBack} disabled={!skip && !minimum && !target} onContinue={() => onSubmit(skip ? { skipped: true } : { skipped: false, minimum: minimum ? Number(minimum) : null, target: target ? Number(target) : null, currency, period })}><label className="check-row"><input type="checkbox" checked={skip} onChange={(event) => setSkip(event.target.checked)} /><span><strong>Skip compensation for now</strong><small>Do not use pay as a preference.</small></span></label>{!skip && <div className="form-grid"><label className="field"><span>Minimum</span><input type="number" min="0" value={minimum} onChange={(event) => setMinimum(event.target.value)} placeholder="100000" /></label><label className="field"><span>Target</span><input type="number" min="0" value={target} onChange={(event) => setTarget(event.target.value)} placeholder="130000" /></label><label className="field"><span>Currency</span><select value={currency} onChange={(event) => setCurrency(event.target.value)}><option>USD</option><option>CAD</option><option>EUR</option><option>GBP</option></select></label><label className="field"><span>Period</span><select value={period} onChange={(event) => setPeriod(event.target.value as "hour" | "year")}><option value="year">Per year</option><option value="hour">Per hour</option></select></label></div>}</Shell>;
}
function ReviewStep({ setup, busy, error, onSubmit, onBack }: StepProps) {
  const roles = setup.roles.filter((role) => role.intent !== "dont_seed").map((role) => role.title).join(", ") || "None";
  const pay = setup.compensation?.skipped ? "Not specified" : [setup.compensation?.minimum, setup.compensation?.target, setup.compensation?.currency, setup.compensation?.period].filter(Boolean).join(" · ");
  const rows = [["Roles", roles, "roles"], ["Location & work mode", [setup.eligibility?.intended_country, setup.location?.accepted_work_modes.join(", "), setup.location?.accepted_onsite_locations.join(", ")].filter(Boolean).join(" · ") || "Not set", "location"], ["Compensation", pay, "compensation"]];
  return <div className="onboarding-content"><p className="eyebrow">Final check</p><h1 id="onboarding-title">Review your preferences</h1><p className="onboarding-lede">Saving creates your settings. Scraping stays off until providers are configured later.</p><div className="review-list">{rows.map(([label, value, section]) => <div className="review-row" key={label}><span>{label}</span><strong>{value}</strong><button onClick={() => onSubmit({ action: "change", section })}>Edit</button></div>)}</div><Actions busy={busy} error={error} onBack={onBack} onContinue={() => onSubmit({ action: "save" })} label="Save and open dashboard" /></div>;
}

export function OnboardingPage({ initial, onComplete }: PageProps) {
  const [status, setStatus] = useState(initial); const [busy, setBusy] = useState(false); const [error, setError] = useState("");
  async function run(action: () => Promise<OnboardingStatus>) { if (busy) return; setBusy(true); setError(""); try { const next = await action(); setStatus(next); if (!next.needs_onboarding) onComplete(); } catch (reason) { setError(reason instanceof Error ? reason.message : "Could not save this step"); } finally { setBusy(false); } }
  const setup = status.setup;
  return <main className="onboarding-shell"><header className="onboarding-topbar"><span className="onboarding-brand"><span className="brand-mark">RB</span> Resume Builder</span><button className="onboarding-skip" onClick={() => { setBusy(true); skipOnboarding().then(onComplete).catch((reason) => { setError(reason instanceof Error ? reason.message : "Could not leave setup"); setBusy(false); }); }} disabled={busy}>Set up later</button></header><section className={status.step === "roles" ? "onboarding-stage wide" : "onboarding-stage"} aria-labelledby="onboarding-title"><Progress status={status} />
    {status.step === "resume" && <ResumeStep busy={busy} error={error} done={() => run(getOnboardingStatus)} />}
    {status.step === "ai_choice" && <AiChoice status={status} busy={busy} error={error} choose={(ai, key) => run(() => startOnboarding(ai, key))} />}
    {status.step === "roles" && setup && <RolesStep setup={setup} busy={busy} error={error} onSubmit={(answer) => run(() => answerOnboarding("roles", answer))} onBack={() => setStatus({ ...status, step: "ai_choice", progress: 1 })} />}
    {status.step === "location" && setup && <LocationStep setup={setup} busy={busy} error={error} onSubmit={(answer) => run(() => answerOnboarding("location", answer))} onBack={() => run(backOnboarding)} />}
    {status.step === "compensation" && setup && <CompensationStep setup={setup} busy={busy} error={error} onSubmit={(answer) => run(() => answerOnboarding("compensation", answer))} onBack={() => run(backOnboarding)} />}
    {status.step === "review" && setup && <ReviewStep setup={setup} busy={busy} error={error} onSubmit={(answer) => run(() => answerOnboarding("review", answer))} onBack={() => run(backOnboarding)} />}
  </section></main>;
}
