# Resume templates

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
