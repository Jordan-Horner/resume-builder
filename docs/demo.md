# Demo walkthrough

The public demo uses the approved Phoenix Wright fictional workspace under
`examples/phoenix-wright/`. Do not record a real private vault or rely on
redaction.

Run the fixture from the engine repository with:

```bash
export RESUME_BUILDER_WORKSPACE="$PWD/examples/phoenix-wright/workspace"
resume-builder validate --strict
resume-builder direction validate
resume-builder synthesis resumes/plans/senior-defense-attorney.yaml
resume-builder preview resumes/baselines/senior-defense-attorney.md
resume-builder mint resumes/baselines/senior-defense-attorney.md
```

## 60-second recording script

**0–8 seconds — Problem**

“Most resume tools rewrite a document. Resume Builder preserves career evidence
so strong accomplishments do not disappear and unsupported claims do not slip
in.”

**8–20 seconds — Evidence vault**

Show one imported source and two canonical fact files. Point out the source ID,
confirmation status, and employment scope.

**20–34 seconds — Plan and draft**

Show a role direction and the synthesis plan. Highlight one story’s job and its
action, object, scope, outcome, and evidence mapping. Then open the resulting
Markdown bullet and its hidden evidence comment.

**34–46 seconds — Preview and edit**

Run the preview command and open the HTML. Make one wording edit, rerun preview,
and show that the current draft replaces the previous preview without a review
detour.

**46–60 seconds — Output**

Open the user-approved HTML preview and audited PDF. End on: “Evidence in; a
role-specific, reviewable, reproducible resume out.”

## Three-minute walkthrough

1. Explain the regression problem in traditional resume editing.
2. Show one of the fixture's registered fictional sources and its applied
   additive hydration plan.
3. Apply canonical facts and show provenance.
4. Select a direction and inspect the synthesis plan.
5. Compile and intentionally demonstrate one blocked unsupported claim.
6. Correct the claim and publish the HTML preview.
7. Make a visible wording edit and refresh the preview.
8. Say `Mint` and create the audited PDF from that current preview.
9. Tailor to a fictional posting and compare it with the baseline.

## Required visuals

- Project health report
- Source-to-fact provenance
- Synthesis story and evidence map
- Blocked unsupported claim
- Preview, edit, and refreshed preview
- Baseline-versus-tailored comparison
- User-approved preview and PDF

## Recording checklist

- Use a clean terminal theme at 1440×900 or larger.
- Increase terminal and editor type to remain readable after compression.
- Hide all notifications and unrelated browser tabs.
- Use fictional names, employers, contact details, sources, and job postings.
- Record the voiceover separately if live narration makes the workflow rushed.
- Export a captioned MP4 and a silent GIF or short loop for the README.
