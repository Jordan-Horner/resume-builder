# Resume rendering contract

Build Markdown resumes through the default career-ops-derived ATS template;
never hand-author final JSON, HTML, or PDF. The Markdown file under `resumes/`
remains the editable source. Everything under `build/` is disposable. Building
and minting are separate lifecycle stages.

## Normal command

```bash
resume-builder preview resumes/baselines/<direction>.md
# edit the Markdown, then preview again
resume-builder preview resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md --max-pages 1
```

`preview` is the normal interactive command. It compiles the current Markdown,
validates its structured evidence and renderer, and publishes HTML in one step.
Edit the Markdown and run `preview` again until the user says `Mint`. `compile`
enforces the
[canonical Markdown contract](markdown-contract.md),
validates evidence and the renderer, and writes JSON plus a reproducibility
manifest with `editorial_status: unreviewed`. It does not publish HTML and never
creates a PDF. It preserves the last published HTML and PDF; their manifests
become stale instead of their files disappearing.
Use `resume-builder compile` directly when diagnosing only that build stage.

When the user explicitly asks for an independent critique, `verify` prepares
the optional review workflow. `review package` writes two pinned inputs. The `.cold.json` file contains only
the target and visible resume blocks for the provisional independent read. The
`.package.json` appendix pins the compiled build, plan, direction, concept and
risk decisions, structured evidence audit, and exact canonical facts for the
subsequent evidence and career review. The generated `.decisions.json` contains
the exact block pins while leaving every judgment to the reviewer. Version 2
decisions may carry a `wording-only` replacement for a rejected block. When the
user already authorized the downstream revision or mint workflow, `review
apply-repairs` applies those exact replacements to the pinned Markdown source,
preserves its evidence annotations, and requires verification plus a fresh
review. It cannot apply fact, authority, chronology, or structural changes.
`review finalize` constructs and validates the version 4 record from the final
decisions.
`review validate` remains a focused diagnostic that checks the record against
both files, the build manifest, every narrative block, and every cited fact hash.

`preview` rebuilds the current Markdown and publishes it for the preview/edit
loop. It does not require or claim an independent language or selection review.
Its structured `user_handoff` marks presentation as required
and supplies the artifact path, absolute path, pending approval state, next
action, organized presentation fields, and ready-to-post `rendered_markdown`.
The agent must post `rendered_markdown` as the user-facing response rather than
printing the command JSON or reducing the handoff to a bare link. Generating the
HTML alone does not complete the preview step. The HTML explicitly identifies
itself as a continuous web preview; PDF page count is calculated only during
minting. `mint` renders that
exact user-reviewed HTML and creates a
separately audited PDF using pinned Playwright Chromium;
install it once with `python -m playwright install chromium`.

Before rendering, the compiler normalizes common ATS-problem Unicode and rejects
numeric claims that do not occur in the specifically cited facts. It reports
low lexical overlap and non-confirmed facts for human review. Mint-time PDF rendering
blocks network requests and page JavaScript, waits for fonts, checks horizontal
overflow, and verifies extractable text on every page and for every factual
block. The version 6 synthesis plan resolves the page budget. `--max-pages N`
may only confirm that same value; change the plan first when the user chooses a
different budget.
Overflow is a failed mint while the diagnostic PDF is retained for inspection.

## Low-level command

```bash
resume-builder render build/<resume-slug>.json \
  --output build/<resume-slug>.html
```

Use `render` only for renderer development or diagnostics. Use
`--template templates/<name>.html` only when the user selects another
repository template. The renderer rejects templates outside `templates/` and
outputs outside `build/`.

## Payload schema

```json
{
  "version": 1,
  "lang": "en",
  "page_format": "letter",
  "candidate": {
    "name": "Candidate Name",
    "headline": "Target role | Strength | Strength",
    "email": "candidate@example.com",
    "location": "City, State",
    "evidence": ["PROFILE-001", "PROFILE-003"]
  },
  "summary": "Evidence-grounded targeted summary.",
  "summary_evidence": ["PROFILE-003", "EX-002"],
  "competencies": [
    {"text": "Incident Response", "evidence": ["SKILL-001", "EX-003"]}
  ],
  "experience": [
    {
      "company": "Example Corp",
      "role": "Support Engineer",
      "dates": "2023 - Present",
      "evidence": ["EX-001"],
      "bullets": [
        {"text": "Improved investigation speed.", "evidence": ["EX-002"]}
      ]
    }
  ],
  "projects": [],
  "education": [],
  "certifications": [],
  "skills": [
    {"category": "Systems", "items": ["Linux", "AWS"], "evidence": ["SKILL-002"]}
  ]
}
```

Every factual object requires one or more canonical fact IDs. The renderer
fails on unknown IDs, unsafe contact URLs, malformed fields, unresolved template
placeholders, or output outside `build/`. Evidence IDs are retained as hidden
`data-evidence` attributes but are not visible in the resume.

Empty optional arrays remove their sections entirely. Use `letter` for US and
Canada unless the user requests otherwise; use `a4` where that is the market
standard. The template uses selectable text, ATS-safe system fonts, standard
headings, a single column, disabled optional ligatures, and print-aware page
breaks. Preserve the established resume palette: teal `#087f8c` for section
accents and blue `#245f8f` for secondary emphasis. Do not substitute purple or
an AI-branded gradient. Original resume artifacts may inform presentation only
when the user explicitly asks to preserve their visual identity; they remain
out of scope for resume wording and factual claims.

`build/resumes/<slug>/resume.manifest.json` records the build's source, template, cited-fact
hashes, compiler version, ATS replacements, evidence findings, warnings, and
generated JSON hash. `build/reviews/<slug>.cold.json` is the isolated
provisional review input, and `build/reviews/<slug>.package.json` is its later
evidence and selection appendix; these exist only after an explicit critique
request. `build/resumes/<slug>/resume.preview.json` pins the current build manifest, HTML, and
pending user-approval state.
`build/resumes/<slug>/resume.mint.json` separately records the
build and preview-manifest hashes, explicit user approval, page budget, PDF
audit, internal PDF hash, and submission-export hash. Successful minting copies
the upload-ready PDF to
`exports/resumes/<resume-slug>/<candidate-name>-Resume.pdf`. Each resume's
internal JSON, HTML, manifests, diagnostics, and audited PDF stay together under
`build/resumes/<resume-slug>/`; the folder retains
the internal targeting context, while the employer-visible filename remains
neutral and never includes the target company. `build/` remains an internal,
disposable workspace; users should retrieve application files from `exports/`.
The manifests make
draft and finalization stages explainable without making generated files
canonical.
