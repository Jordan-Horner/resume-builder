# Resume template contract

Resume Builder supports multiple presentation preferences without allowing
formatting choices to rewrite the career argument. A resume template has two
independent layers:

1. A **content template** under `templates/resume-templates/<id>.yaml` controls
   canonical sections, whether each is required, optional, or forbidden, and
   the order of every visible section. Version 1 keeps canonical ATS-safe
   section headings fixed.
2. A **visual theme** under `templates/themes/<id>.yaml` identifies an HTML
   renderer under `templates/`. It controls typography, color, spacing, and
   print behavior. A registered theme must contain every required document and
   print-style placeholder, exactly one of each data-bearing header, preview,
   and `{{RESUME_SECTIONS}}` placeholder, and no legacy per-section placeholders,
   so it cannot discard resume data or choose a new content hierarchy.

Version 7 synthesis plans declare both choices:

```yaml
resume_template:
  content: technical-classic
  theme: clean-teal
```

## Built-in content templates

### `technical-classic`

Use this default when the user has not selected another structure. It requires
Professional Summary, Work Experience, and Technical Skills; allows Selected
Projects, Education, and Certifications; forbids Core Competencies; and places
Technical Skills last.

### `technical-skills-first`

Use this only when the user prefers early technology visibility. It has the
same allowed sections as `technical-classic`, but places Technical Skills after
the summary and before experience. It does not convert skills into competency
labels.

## Boundaries

- Content templates control section presence and order. Version 1 uses fixed
  canonical headings; a future heading-label capability requires a versioned
  schema change.
- Synthesis controls evidence selection, story allocation, role arcs, and
  omissions. A template never imposes a universal bullet count.
- Every visible factual block remains subject to canonical evidence and review.
- Core Competencies may appear only in a template that allows or requires it
  and when the synthesis presentation decision independently gives it a
  distinct scanning job.
- A category-prefixed inventory of tools belongs in Technical Skills, never in
  Core Competencies.
- A user may choose a different named content template or theme. Add new
  registry files instead of changing the meaning of an existing ID.
- Built-in IDs are immutable. Install missing built-ins in an existing
  workspace with `resume-builder workspace templates sync`; synchronization
  never overwrites a workspace-owned file.
- Template exceptions require a new named template when they change section
  architecture. Per-resume prose and story decisions remain in the synthesis
  plan rather than being encoded into a template.

Compilation rejects missing required sections, forbidden sections, section
order drift, a competency decision that conflicts with the selected content
template, or a renderer that conflicts with the selected theme.
The build manifest pins the content-template YAML, theme YAML, and renderer
HTML. Changing any one invalidates the build and its dependent reviews.
