# Resume regression cases

Regression cases verify that a newly generated directional baseline preserves
material evidence from a suitable earlier resume while gaining useful evidence
from the broader vault. A case belongs here only when there is a real prior
resume in the same lane with a stable registered source and meaningful facts to
preserve.

Do not add cases merely so every baseline has one. An exploratory baseline such
as Customer Success, or a new direction without a comparable original, is
covered by synthesis validation, compilation, direction audit, and critique
until a legitimate regression source exists. `sealed: true` means the
deterministic comparison and its separate editorial review have been accepted;
it is not a permanent claim that the resume cannot improve.

Run:

```bash
resume-builder eval validate
resume-builder eval grade evals/cases/<case>.yaml
```

## Summary-positioning evaluations

`summary-positioning.yaml` is a public, fictional decision matrix for changes to
the summary-planning and independent language-review standards. It covers
direct, adjacent, and exploratory targeting, including cases where a formal
title differs from demonstrated work, one substantial project supplies enough
evidence, a broad professional identity is correct, or a target identity would
overstate the evidence.

These cases are semantic reviewer evaluations rather than deterministic keyword
rules. Unit tests validate their coverage, expected decisions, and public-safe
content. Before merging a material summary-positioning change, give each case to
a fresh reviewer with only its target, visible evidence profile, proposed
opening, and the current language-review standard. Every decision must match the
recorded expectation without relying on exact-title matching.
