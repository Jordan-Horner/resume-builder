# Canonical resume Markdown contract

Markdown under `resumes/` is the only editable resume source. Use this strict
version 1 structure so `resume-builder compile` can account for every factual
field and reject silent content loss.

## Frontmatter

Begin with YAML containing only `version`, `lang`, `page_format`, and
`candidate`. Candidate contact links use `{url, display}` objects. Ground the
header with canonical fact IDs.

```yaml
---
version: 1
lang: en
page_format: letter
candidate:
  name: Candidate Name
  headline: Target Role | Strength | Strength
  phone: (555) 555-5555
  email: candidate@example.com
  location: City, State
  linkedin:
    url: https://www.linkedin.com/in/example
    display: linkedin.com/in/example
  github:
    url: https://github.com/example
    display: github.com/example
  portfolio:
    url: https://example.com
    display: example.com
  evidence: [PROFILE-001, PROFILE-003]
---
```

The renderer requires a name, headline, evidence, and at least one contact
field. Only HTTP(S) URLs are accepted.

## Sections

For version 7 or later synthesis plans, include and order these canonical sections
according to the selected content template. The Markdown source order is
compiled into `section_order` and validated before rendering.

Use the following level-one headings. `Professional Summary` is required; the
others are optional and disappear from rendered output when omitted.

```markdown
# Professional Summary

One compact, factual paragraph. <!-- evidence: PROFILE-003 EX-002 -->

# Core Competencies

- Incident Response <!-- evidence: SKILL-001 -->

# Work Experience

## Company | Role | Dates | Optional location <!-- evidence: EX-001 -->

- Accomplishment or responsibility. <!-- evidence: EX-002 -->

# Selected Projects

## Project name <!-- evidence: PROJECT-001 -->

Project description. <!-- evidence: PROJECT-001 -->

**Technologies:** Python, AWS <!-- evidence: PROJECT-001 -->

# Education

- Credential | Institution | Optional year | Optional detail <!-- evidence: EDU-001 -->

# Certifications

- Certification | Optional issuer | Optional year <!-- evidence: CERT-001 -->

# Technical Skills

- **Category:** Skill, Skill <!-- evidence: SKILL-002 -->
```

`Professional Experience`, `Summary`, `Projects`, and `Skills` are accepted
heading aliases. Do not add unrecognized level-one sections until the compiler
contract and renderer support them; compilation fails rather than dropping
their content.

Evidence comments may follow the factual text on the same line or on an
indented continuation line. Every factual block requires at least one canonical
fact ID. Comments remain in Markdown, become structured evidence in the
generated JSON, and are hidden as `data-evidence` attributes in HTML.

## Compilation

```bash
resume-builder compile resumes/baselines/<direction>.md
resume-builder review package resumes/baselines/<direction>.md
resume-builder review validate build/reviews/<direction>.json
resume-builder preview resumes/baselines/<direction>.md
resume-builder mint resumes/baselines/<direction>.md
```

The first command writes review-input JSON and a build manifest under
`build/resumes/<resume-slug>/`;
it publishes neither HTML nor PDF. The review-package command writes a cold-read
input and a separate evidence appendix. After a fresh career-professional
review is approved and validated, `preview` publishes the exact reviewed build
as HTML for the user's final review. The separate `mint` command renders that
exact reviewed HTML after explicit final approval,
uses pinned Playwright Chromium, and audits layout, page count, and text
extraction. A successful mint keeps its per-resume diagnostics under
`build/resumes/<resume-slug>/` and publishes
the upload-ready PDF under `exports/resumes/<resume-slug>/` with the neutral
`<candidate-name>-Resume.pdf` filename. Install Chromium once with
`python -m playwright install chromium`.
Use `--browser PATH` only to test a specific Chromium executable. Mint enforces
the page budget resolved in a version 6 synthesis plan; an explicit
`--max-pages N` must agree with that plan.
