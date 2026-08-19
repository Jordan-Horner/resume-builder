# Resume rendering contract

Build Markdown resumes through the default career-ops-derived ATS template;
never hand-author final JSON, HTML, or PDF. The Markdown file under `resumes/`
remains the editable source. Everything under `build/` is disposable. Building
and minting are separate lifecycle stages.

## Normal command

```bash
resume-builder verify resumes/baselines/<direction>.md
resume-builder review apply-repairs build/reviews/<direction>.decisions.json
resume-builder review finalize build/reviews/<direction>.decisions.json
resume-builder review validate build/reviews/<direction>.json
resume-builder preview resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md --max-pages 1
```

`verify` is the normal review handoff. It orchestrates compilation, direction
and optional target checks, prose preflight, and review packaging; writes a
compact hash-pinned receipt; and reuses unchanged results. The underlying
commands remain independently callable for diagnostics. `compile` enforces the
[canonical Markdown contract](markdown-contract.md),
validates evidence and the renderer, and writes JSON plus a reproducibility
manifest with `editorial_status: unreviewed`. It does not publish HTML and never
creates a PDF. It preserves the last published HTML and PDF; their manifests
become stale instead of their files disappearing.
Use `resume-builder compile` directly when diagnosing only that build stage.

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

`preview` never rebuilds reviewed content. It renders the exact compiled JSON
and template pinned by the approved review, then publishes that HTML for final
user review. Its notice separately reports evidence integrity, career review,
role-fit judgment, career verdict, and pending user approval; the notice never
appears in print. The HTML explicitly identifies itself as a continuous web
preview; PDF page count is calculated only during minting. `mint` renders that
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

`build/<slug>.manifest.json` records the build's source, template, cited-fact
hashes, compiler version, ATS replacements, evidence findings, warnings, and
generated JSON hash. `build/reviews/<slug>.cold.json` is the isolated
provisional review input, and `build/reviews/<slug>.package.json` is its later
evidence and selection appendix. `build/<slug>.preview.json` pins the approved review,
build manifest, reviewed HTML, and pending final-user-approval state.
`build/<slug>.mint.json` separately records the
build and preview-manifest hashes, explicit user approval, page budget, PDF
audit, and PDF hash. The manifests make
draft and finalization stages explainable without making generated files
canonical.
