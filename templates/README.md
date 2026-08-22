# Resume templates

Resume Builder separates reusable content architecture from visual styling:

- `resume-templates/*.yaml` defines allowed sections, required sections, and
  their order. `technical-classic` is the default evidence-first layout;
  `technical-skills-first` is an alternate layout for users who want the skills
  inventory nearer the top.
- `themes/*.yaml` names a visual theme and points to its HTML renderer.
- `themes/clean-teal.html` is the strict renderer used by the built-in
  `clean-teal` theme. `resume-template.html` remains the legacy default for
  synthesis plans before version 7.

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
Normal lifecycle commands resolve the selected theme from the synthesis plan;
`--template` remains an explicit diagnostic override and must agree with a
version 7 plan.

Existing workspaces can install missing built-ins without overwriting custom
files:

```bash
resume-builder workspace templates sync
```

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
