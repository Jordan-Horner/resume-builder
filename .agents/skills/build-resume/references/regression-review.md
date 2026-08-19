# Resume regression review

## Before editing

For an existing resume, inspect:

1. the current working-tree file;
2. its most recent committed version;
3. relevant earlier Git versions when wording or content may have regressed;
4. the directional baseline when updating a tailored resume.

If the path is new, state that no prior resume version exists.

## Fresh-baseline source comparison

When a fresh baseline has a registered original resume for the same direction,
finish and compile the new draft before opening that original. Then compare the
original's substantive evidence with the new draft and classify it as:

- **Retained:** the same career evidence remains clearly represented.
- **Strengthened:** evidence is combined, prioritized, or contextualized more
  effectively without changing the supported claim.
- **Intentionally omitted:** the evidence remains in the vault but is excluded
  for direction fit, duplication, evidence strength, or page budget.
- **Vault gap:** potentially valuable source information is not represented by a
  canonical fact and must route through hydration before use.
- **Regression:** relevant supported evidence was lost, weakened, assigned to
  the wrong role, or made less credible without a documented reason.

Also identify evidence used from other source resumes that makes the new
baseline more complete than the lane-specific original. This is an evidence
coverage audit, not a wording-similarity test: shared names, metrics, tools, and
precise technical terms are expected. Never rewrite accurate content solely to
reduce textual overlap.

A new baseline does not pass this comparison while it contains an unexplained
material regression. Resolve the presentation from existing facts, route a
vault gap through hydration, or disclose an intentional tradeoff before
finishing. Use `critique-resume` separately for the full editorial quality
judgment.

## Required comparison

Before finishing, classify material changes as:

- **Added:** new bullet, section, metric, skill, employer, or evidence link.
- **Removed:** content present in the previous version but absent now.
- **Rewritten:** meaning, scope, ownership, certainty, or emphasis changed.
- **Reordered:** content moved without a material wording change.
- **Evidence changed:** fact IDs were added, removed, or replaced.

Report substantive changes; ignore formatting-only noise. For each removal or
meaning-changing rewrite, explain why it serves the target and whether the
information remains preserved in the vault or baseline.

## Safeguards

- Obtain confirmation before removing or weakening approved content from an
  existing resume.
- Never remove content merely to make a diff smaller or satisfy a page target;
  show the tradeoff first.
- Never treat omission from a tailored resume as deletion from its baseline or
  the vault.
- Never use an older resume as factual authority when its claim is absent from
  the vault; surface the discrepancy for hydration or review.
- Preserve manual wording unless the change is intentional and disclosed.
- Keep baseline and tailored resume histories independent.

## Completion summary

Return a compact summary containing:

- output path and target;
- additions;
- removals;
- material rewrites;
- evidence changes;
- unresolved questions or `needs-review` facts;
- validation and rendering status.
- for a fresh baseline, the source-comparison classifications and evidence gained
  from other registered resumes.
