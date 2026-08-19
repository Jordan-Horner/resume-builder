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
