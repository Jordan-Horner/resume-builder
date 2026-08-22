# Resume rendering contract

Build Markdown resumes through the default career-ops-derived ATS template;
never hand-author final JSON, HTML, or PDF. The Markdown file under `resumes/`
remains the editable source. Everything under `build/` is disposable. Building
and minting are separate lifecycle stages.

Version 7 or later synthesis plans select a named content template and a separate visual
theme. The content template supplies the compiled `section_order`; the theme
must retain every required document and print-style placeholder, render exactly
one of each data-bearing header, preview, and `{{RESUME_SECTIONS}}` placeholder,
and may not use legacy per-section placeholders or rearrange the section stream.
The content template, theme definition, renderer, optional version 2
stylesheet, and final renderer composition are hash-pinned lifecycle inputs.
Compile, verify, preview, and mint use the plan-selected theme by default; an
explicit conflicting `--template` is rejected.

## Normal command

```bash
resume-builder compile resumes/baselines/<direction>.md
resume-builder review route resumes/baselines/<direction>.md
resume-builder review language-package resumes/baselines/<direction>.md
resume-builder review language-finalize build/reviews/<direction>.language.decisions.json
resume-builder preview resumes/baselines/<direction>.md
# edit the Markdown, then compile and review only changed blocks
resume-builder preview resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md --max-pages 1
```

`preview` is the normal interactive presentation command. It reuses the current
compiled Markdown and current independent language record, validates their
pins, and publishes HTML. Edit the Markdown, compile it, complete the changed-
block language review, and run `preview` again until the user says `Mint`.
`compile` enforces the
[canonical Markdown contract](markdown-contract.md),
validates evidence and the renderer, and writes JSON plus a reproducibility
manifest with `editorial_status: unreviewed`. It does not publish HTML and never
creates a PDF. It preserves the last published HTML and PDF; their manifests
become stale instead of their files disappearing.
Use `resume-builder compile` directly when diagnosing only that build stage.

Every draft first uses `review language-package`. Its
`.language.cold.json` file contains all narrative blocks on the first pass and
only new or changed blocks on later passes, with visible neighbor context.
It also carries a versioned `review_standard` whose general context test asks
whether the visible block identifies the actor, action, object, and
reader-relevant value without requiring an invented premise, mechanism, or
relationship. Keep the standard free of candidate examples and personal
editorial rules so engine tests never need private resume prose.
`review language-finalize` carries exact approved unchanged blocks into the new
hash-pinned record. When hybrid routing selects the deeper review or the user
explicitly requests it, `verify` prepares the strategy and hiring workflow.
Selection freshness is based on a prose-independent strategy digest covering
the chosen stories, evidence, exclusions, role allocation, direction, and
target. Sentence wording, plan rationale prose, and word-count diagnostics do
not reopen selection review. After a changed block passes the standalone
language review, an unchanged sealed strategy may also carry forward the prior
hiring verdict; a target, direction, evidence, selection, exclusion, or role-
allocation change still requires the appropriate deeper review.
`review package` writes two pinned inputs. The `.cold.json` file contains only
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

`preview` publishes the current compiled Markdown for the preview/edit loop. It
requires and reports the standalone independent language review. It requires
the deeper critique only when hybrid routing selected that branch.
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

Use `render` only for renderer development or diagnostics. Normal resume work
selects a registered content template and visual theme in the synthesis plan.
Use `--template templates/<name>.html` only as a diagnostic override. The
renderer rejects templates outside `templates/` and outputs outside `build/`.

Version 1 visual themes may point to complete HTML renderers. Version 2 themes
compose a local stylesheet into exactly one `{{THEME_CSS}}` placeholder in a
shared renderer. The stylesheet cannot import remote resources, use
`url(...)`, or close the surrounding style tag. This feature changes HTML and
PDF presentation only; it does not add DOCX, LaTeX, image, script, or remote
font backends.

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
breaks. The default `clean-teal` theme preserves teal `#087f8c` for section
accents and blue `#245f8f` for secondary emphasis. Other named themes may
define a distinct restrained ATS-safe palette; do not introduce AI-branded
gradients. Original resume artifacts may inform presentation only
when the user explicitly asks to preserve their visual identity; they remain
out of scope for resume wording and factual claims.

`build/resumes/<slug>/resume.manifest.json` records the build's source, template, cited-fact
hashes, compiler version, ATS replacements, evidence findings, warnings, and
generated JSON hash. `build/reviews/<slug>.language.cold.json` and
`build/reviews/<slug>.language.json` are the always-on isolated language input
and current decision record. `build/reviews/<slug>.cold.json` is the isolated
full-critique prose input, and `build/reviews/<slug>.package.json` is its later
evidence and selection appendix; those deeper artifacts exist only when hybrid
routing or the user requests the career review.
`build/resumes/<slug>/resume.preview.json` pins the current build manifest,
language record, HTML, and pending user-approval state.
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
When a preview is pinned to a real posting, its browser title, preview handoff,
and mint result identify the target as `<company> — <role>`. The preview stores
that validated job context for minting, and the job-aware HTML title flows into
PDF metadata without adding targeting text to the visible resume. The neutral
employer-upload filename remains unchanged.
The manifests make
draft and finalization stages explainable without making generated files
canonical.
