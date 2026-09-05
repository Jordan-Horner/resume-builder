import { useRef, useState } from "react";
import { uploadResume } from "../api";

export interface ImportedCareerMaterial {
  name: string;
  alreadyRegistered: boolean;
}

interface Props {
  onImported?: (items: ImportedCareerMaterial[]) => void;
}

export function CareerMaterialUploader({ onImported }: Props) {
  const [files, setFiles] = useState<File[]>([]);
  const [imported, setImported] = useState<ImportedCareerMaterial[]>([]);
  const [dragging, setDragging] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const input = useRef<HTMLInputElement>(null);

  function remember(items: ImportedCareerMaterial[]) {
    setImported((current) => {
      const combined = [...current];
      for (const item of items) {
        if (!combined.some((existing) => existing.name === item.name)) combined.push(item);
      }
      return combined;
    });
    onImported?.(items);
  }

  function select(next: FileList | File[]) {
    setFiles(Array.from(next));
    setError("");
  }

  async function submit() {
    if (!files.length || uploading) return;
    setUploading(true);
    setError("");
    const completed: ImportedCareerMaterial[] = [];
    try {
      for (const file of files) {
        const result = await uploadResume(file);
        completed.push({
          name: result.filename,
          alreadyRegistered: Boolean(result.already_registered),
        });
      }
      remember(completed);
      setFiles([]);
      if (input.current) input.current.value = "";
    } catch (reason) {
      remember(completed);
      setFiles((current) => current.slice(completed.length));
      if (input.current) input.current.value = "";
      setError(reason instanceof Error ? reason.message : "Could not add these files.");
    } finally {
      setUploading(false);
    }
  }

  return <div className="career-material-uploader">
    {imported.length > 0 && <div className="resume-import-list" aria-label="Imported career material">{imported.map((item) => <div className="resume-file-receipt" key={item.name}>
      <span className="receipt-file-mark" aria-hidden="true">DOC</span>
      <span><strong>{item.name}</strong><small>{item.alreadyRegistered ? "Already part of your career evidence" : "Added to your career evidence"}</small></span>
      <span className="receipt-status">Ready</span>
    </div>)}</div>}
    <div className={`${dragging ? "resume-dropzone dragging" : "resume-dropzone"}${imported.length ? " compact" : ""}`} onDragEnter={(event) => { event.preventDefault(); setDragging(true); }} onDragOver={(event) => event.preventDefault()} onDragLeave={() => setDragging(false)} onDrop={(event) => { event.preventDefault(); setDragging(false); select(event.dataTransfer.files); }}>
      <span className="file-glyph" aria-hidden="true">↥</span>
      <strong>{files.length ? `${files.length} ${files.length === 1 ? "file" : "files"} selected` : imported.length ? "Add more career material" : "Drop resumes or a LinkedIn profile PDF here"}</strong>
      <span>{files.length ? files.map((file) => file.name).join(" · ") : "PDF, DOCX, Markdown, HTML, or text · 10 MB per file"}</span>
      <input ref={input} type="file" multiple accept=".pdf,.docx,.md,.txt,.html,.htm,.tex" onChange={(event) => event.target.files && select(event.target.files)} />
      <div className="career-material-actions">
        <button type="button" className="secondary-button" onClick={() => input.current?.click()} disabled={uploading}>{imported.length ? "Add more" : files.length ? "Choose different files" : "Choose files"}</button>
        {files.length > 0 && <button type="button" className="onboarding-primary" onClick={submit} disabled={uploading}>{uploading ? "Adding…" : `Add ${files.length} ${files.length === 1 ? "source" : "sources"}`}</button>}
      </div>
    </div>
    {error && <p className="onboarding-error" role="alert">{error}</p>}
  </div>;
}
