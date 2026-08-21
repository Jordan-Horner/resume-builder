# Resumes

This directory contains canonical, versioned resume Markdown.

- `baselines/` holds one stable Markdown file per long-term resume direction.
- `tailored/` holds company-and-role-specific Markdown resumes derived from a
  baseline.

Hydration must never write here. Resume builders create reviewable
Markdown changes using the canonical structure documented in
`.agents/skills/build-resume/references/markdown-contract.md`. Use
`resume-builder feedback resolve <plan> --include-open` before user-driven
revisions. Direct user criticism is first recorded as a temporary session.
Apply the edit and run `resume-builder preview` immediately; repeat that
preview/edit loop until the user says `Mint`. Then promote each intended session with
`resume-builder feedback accept FB-<session> --preview
build/<resume>.preview.json`, then create the audited PDF with
`resume-builder mint`. The mint request is approval of that exact current
preview. Leave every generated artifact under `build/`. Use
`resume-builder verify` and `critique-resume` only for an explicitly requested
independent critique; their records do not gate preview or mint.

Plans under `plans/` keep the evidence strategy reviewable. Existing version 1
plans remain valid and require every planned story. Version 2 plans add a
resume-specific summary job, summary evidence, and `core` versus `supporting`
story importance. The compiler requires core stories and records any omitted
supporting stories in the build manifest instead of silently losing them.
Version 3 also records target mode, complete
direction-concept fit, reviewer risks, and the presentation strategy so those
decisions can be reviewed independently of the resume prose. Version 4 is the
focused-claim format: each story declares one claim focus, a minimum core
evidence set, and a larger optional evidence pool. The compiler reports optional
facts left unused instead of forcing every selected fact into the bullet.
Version 5 adds role arcs that make story
allocation explicit without imposing a fixed bullet count. The compiler checks
that every experience story belongs to one arc and reports the planned and used
stories, distinct jobs, and supported signals intentionally omitted for each
role placement. Version 6 is the default for new work: it resolves the page
budget, separates required role dimensions and stories from optional stories,
and assigns exact evidence to each claim's action, object, scope, and outcome.
This prevents one cited fact from lending unsupported authorship or impact to
another fact in the same bullet.

Job-specific tailoring also requires a preserved posting under `targets/`.
Never overwrite the baseline with the tailored version; Git history preserves
revisions within each stable file. Matching and independent critique remain
available on request but do not interrupt the preview/edit loop.
