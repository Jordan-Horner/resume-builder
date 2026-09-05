import { useEffect, useState } from "react";
import { getResumes } from "../api";
import { EmptyState, ErrorMessage } from "../components";
import type { CareerResume, ResumeLibrary } from "../types";

function ResumeRow({ resume, open }: { resume: CareerResume; open: (resume: CareerResume) => void }) {
  return <button className="career-row resume-library-row resume-row-button" disabled={!resume.preview_url} onClick={() => open(resume)}>
    <div className="career-row-main">
      <div className="career-row-title"><h3>{resume.name}</h3></div>
      <p>{resume.detail}</p>
      {resume.error && <small className="error-text">{resume.error}</small>}
      {resume.preview_message && <small>{resume.preview_message}</small>}
    </div>
    <div className="career-row-meta"><span className={`resume-state ${resume.status_tone}`}>{resume.status_label}</span>{resume.updated_at && <time dateTime={resume.updated_at}>{new Date(resume.updated_at).toLocaleDateString()}</time>}<span className="resume-open-label">View preview →</span></div>
  </button>;
}

export function ResumesPage() {
  const [library, setLibrary] = useState<ResumeLibrary | null>(null);
  const [selected, setSelected] = useState<CareerResume | null>(null);
  const [error, setError] = useState("");
  const load = () => { setError(""); getResumes().then(setLibrary).catch((reason: unknown) => setError(reason instanceof Error ? reason.message : "Could not load resumes.")); };
  useEffect(load, []);
  if (error) return <section className="page"><ErrorMessage message={error} retry={load} /></section>;
  if (!library) return <section className="page" role="status">Loading resumes…</section>;
  function open(resume: CareerResume) {
    if (!resume.preview_url) return;
    setSelected(resume);
  }
  if (selected?.preview_url) return <section className="resume-reader-page">
    <header className="resume-reader-toolbar">
      <button className="text-button" onClick={() => setSelected(null)}>← Back to resumes</button>
      <div><strong>{selected.name}</strong><span>{selected.detail}</span></div>
      <a className="secondary-button" href={selected.preview_url} target="_blank" rel="noreferrer">Open in new tab</a>
    </header>
    <iframe className="resume-document-frame" src={selected.preview_url} title={`${selected.name} preview`} />
  </section>;
  const hasResumes = library.sections.some((section) => section.items.length > 0);
  return <section className="page career-page">
    <header className="career-heading"><div><p className="eyebrow">Career documents</p><h1>Resumes</h1><p className="page-intro">Stable, evidence-backed views of your career. Your vault remains the source of truth.</p></div></header>
    {!hasResumes ? <EmptyState title="No resumes yet">Upload an existing resume to begin building your career vault.</EmptyState> : library.sections.map((section) => (
      <section className="career-section" aria-labelledby={`resume-${section.id}`} key={section.id}>
        <div className="career-section-heading"><div><h2 id={`resume-${section.id}`}>{section.title}</h2><p>{section.description}</p></div><span className="section-count">{section.items.length}</span></div>
        {section.items.length ? section.items.map((resume) => <ResumeRow key={resume.id} resume={resume} open={open} />) : <p className="career-section-empty">Nothing here yet.</p>}
      </section>
    ))}
  </section>;
}
