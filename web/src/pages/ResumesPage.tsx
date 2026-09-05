import { useEffect, useState } from "react";
import { getResumes } from "../api";
import { EmptyState, ErrorMessage } from "../components";
import { CareerMaterialUploader } from "../components/CareerMaterialUploader";
import type { CareerResume, ResumeLibrary } from "../types";
import { useAssistant } from "../assistant/AssistantProvider";

function ResumeRow({ resume, open }: { resume: CareerResume; open: (resume: CareerResume) => void }) {
  return <button className="career-row resume-library-row resume-row-button" disabled={!resume.preview_url} onClick={() => open(resume)} aria-label={resume.preview_url ? `Open ${resume.name}` : undefined}>
    <div className="career-row-main">
      <div className="career-row-title"><h3>{resume.name}</h3></div>
      <p>{resume.detail}</p>
      {resume.error && <small className="error-text">{resume.error}</small>}
      {resume.preview_message && <small>{resume.preview_message}</small>}
    </div>
    <div className="career-row-meta">{resume.updated_at && <time dateTime={resume.updated_at}>{new Date(resume.updated_at).toLocaleDateString()}</time>}</div>
  </button>;
}

export function ResumesPage() {
  const assistant = useAssistant();
  const [library, setLibrary] = useState<ResumeLibrary | null>(null);
  const [selected, setSelected] = useState<CareerResume | null>(null);
  const [showImporter, setShowImporter] = useState(false);
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
      <div className="resume-reader-title"><strong>{selected.name}</strong><span>{selected.detail}</span></div>
      <div className="resume-reader-actions">
        {selected.kind === "directional" && <button className="secondary-button" onClick={() => assistant.discuss(selected.id, selected.name)}>Discuss résumé</button>}
        <a className="secondary-button" href={selected.preview_url} target="_blank" rel="noreferrer">Open in new tab</a>
      </div>
    </header>
    <iframe className="resume-document-frame is-dimmed" src={selected.preview_url} title={`${selected.name} preview`} />
  </section>;
  const hasResumes = library.sections.some((section) => section.items.length > 0);
  return <section className="page career-page">
    <header className="career-heading"><div><p className="eyebrow">Career documents</p><h1>Resumes</h1><p className="page-intro">Directional resumes you can reuse and tailored versions attached to specific jobs.</p></div><button className="secondary-button" onClick={() => setShowImporter((visible) => !visible)}>{showImporter ? "Close" : "Add career material"}</button></header>
    {showImporter && <section className="career-import-panel" aria-labelledby="career-import-title"><div><h2 id="career-import-title">Add source material</h2><p>Upload additional resumes or a LinkedIn profile PDF. They add evidence to your private career record without replacing or rewriting these resumes.</p></div><CareerMaterialUploader /></section>}
    {!hasResumes ? <EmptyState title="No generated resumes yet">Add source material, then ask the agent to build a directional resume.</EmptyState> : library.sections.map((section) => (
      <section className="career-section" aria-labelledby={`resume-${section.id}`} key={section.id}>
        <div className="career-section-heading"><div><h2 id={`resume-${section.id}`}>{section.title}</h2><p>{section.description}</p></div><span className="section-count">{section.items.length}</span></div>
        {section.items.length ? section.items.map((resume) => <ResumeRow key={resume.id} resume={resume} open={open} />) : <p className="career-section-empty">Nothing here yet.</p>}
      </section>
    ))}
  </section>;
}
