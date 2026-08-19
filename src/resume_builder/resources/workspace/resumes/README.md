# Resumes

This directory contains canonical, versioned resume Markdown.

- `baselines/` holds one stable Markdown file per long-term resume direction.
- `tailored/` holds company-and-role-specific Markdown resumes derived from a
  baseline.

Hydration must never write here. Resume builders create reviewable
Markdown changes using the canonical structure documented in
`.agents/skills/build-resume/references/markdown-contract.md`. Use
`resume-builder feedback resolve <plan> --include-open` before user-driven
revisions. Direct user criticism is first recorded as a temporary session and
its latest revision is checked after the independent cold review. After the user
accepts the reviewed preview, promote each intended session with
`resume-builder feedback accept FB-<session> --preview
build/<resume>.preview.json`; unchanged effective guidance preserves that
preview for minting.
Use
`resume-builder verify` for the normal review handoff: it compiles the draft,
runs the fast content checks, writes a cached verification receipt, and prepares
the frozen cold-read package plus reviewer decisions file. Complete that file
through `critique-resume`. When an already-authorized workflow has one clear
wording-only repair, run `resume-builder review apply-repairs`, re-verify, and
repeat the independent review without pausing. Then run `resume-builder review finalize` to create
and validate the version 4 record. After approval, run `resume-builder preview`
to publish a continuous web preview. Create the audited final PDF with
`resume-builder mint` only after explicit final approval. Leave every generated
artifact under `build/`.

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
Pass the target and baseline to `resume-builder verify` so its receipt includes
exact retrieval gains, evidence removals, and semantic gaps before critique or
minting. Compilation is always an unreviewed draft. The verifier runs
`review package`; have `critique-resume` decide every narrative
block from the isolated cold-read file before consulting the evidence appendix;
`resume-builder review finalize` and `resume-builder review validate` must pass before the prose is considered
approved or a web preview can be published. Never overwrite the baseline with the
tailored version; Git history preserves revisions within each stable file.
When accepted rules or open revisions apply, the decisions file includes a
separate post-cold feedback-compliance review. The cold reviewer never receives
that guidance.
