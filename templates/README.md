# Resume templates

Resume Builder separates reusable content architecture from visual styling:

- `resume-templates/*.yaml` defines allowed sections, required sections, and
  their order. `technical-classic` is the default evidence-first layout;
  `technical-skills-first` is an alternate layout for users who want the skills
  inventory nearer the top.
- `renderers/*.html` contains shared, strictly validated HTML document shells.
- `themes/*.yaml` registers a visual theme. Version 2 themes point to a shared
  renderer and a self-contained stylesheet under `themes/*.css`.
- `resume-template.html` remains the legacy default for synthesis plans before
  version 7.

Version 7 synthesis plans select both layers explicitly:

```yaml
resume_template:
  content: technical-classic
  theme: clean-teal
```

Content templates control structure, not evidence selection or bullet counts.
Visual themes control appearance and must not silently reorder sections.
Registered themes must render exactly one `{{RESUME_SECTIONS}}` placeholder
and may not use legacy per-section placeholders.
Version 2 themes also require exactly one `{{THEME_CSS}}` placeholder in their
renderer. Resume Builder composes the stylesheet into that placeholder before
rendering, so preview and PDF output remain one self-contained document.
Normal lifecycle commands resolve the selected theme from the synthesis plan;
`--template` remains an explicit diagnostic override and must agree with a
version 7 plan.

Existing workspaces can install missing built-ins without overwriting custom
files:

```bash
resume-builder workspace templates sync
resume-builder workspace templates list
resume-builder workspace templates validate
resume-builder workspace templates scaffold theme my-theme
resume-builder workspace templates scaffold content my-layout
```

`sync` recursively discovers packaged template files and installs only files
that are missing. It never overwrites a workspace file. `list` identifies each
valid template, its schema version, and whether its descriptor still matches a
built-in. `validate` checks the complete registry, or accepts one template ID.
`scaffold` creates a workspace-owned version 2 starting point and refuses to
replace an existing file.

## Theme schema

Version 1 remains supported for existing workspaces whose theme descriptor
points directly to a complete HTML renderer. New themes should use version 2:

```yaml
version: 2
id: minimal-black
display_name: Minimal Black
description: Conservative monochrome technical resume
category: conservative
renderer: templates/renderers/ats-single-column.html
stylesheet: templates/themes/minimal-black.css
```

Theme stylesheets must be local, nonempty CSS. Remote imports, `url(...)`
references, and closing `</style>` text are rejected. This keeps HTML and PDF
output deterministic, offline, and ATS-safe. Themes do not support scripts,
remote fonts, images, or alternate output backends.

`clean-teal` is the default compatible theme. `minimal-black` is the built-in
version 2 example. Both use the same section stream and therefore change only
presentation. The build manifest pins the descriptor, renderer, stylesheet,
and final composition digest; changing any of them makes the build stale.

## Adding a built-in

Packaged files under `src/resume_builder/resources/templates/` are the install
source. Keep the top-level `templates/` tree as its byte-for-byte development
mirror. Recursive discovery means a new renderer, theme descriptor, or
stylesheet does not require editing a Python resource list. Add validation and
composition tests with every built-in theme.

`resume-template.html` is the default ATS-safe presentation layer for Resume
Builder. It is adapted from the proven career-ops CV template while remaining
independent from career-ops data and workflows.

The template preserves the lessons that matter for reliable resume output:

- single-column layout with standard section names;
- selectable text with ATS-safe system fonts;
- disabled optional ligatures to prevent corrupted PDF extraction;
- no sidebars, icons, images, nested tables, or critical headers and footers;
- restrained color, predictable print margins, and careful page-break rules;
- optional sections that disappear when they contain no content;
- hidden `data-evidence` attributes that preserve validated vault fact IDs.
- a screen-only review-state notice that identifies the HTML as a continuous
  web preview and is excluded from printed and minted output.

Normal resume work must use `resume-builder preview`; it rebuilds and publishes
the current editable draft without requiring a critique.
The low-level renderer remains available for template development and
diagnostics. Agents must never
hand-edit rendered HTML:

```bash
resume-builder render build/support-operations.json \
  --output build/support-operations.html
```

The Markdown file under `resumes/` remains the editable resume source. HTML and
PDFs under `build/` are replaceable output.
