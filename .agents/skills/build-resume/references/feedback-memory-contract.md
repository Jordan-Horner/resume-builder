# Conversational feedback memory contract

Use feedback memory when the user asks to edit, replace, shorten, remove, or
reframe visible resume prose, or says that wording is inaccurate, unnatural, or
otherwise undesirable.

## Two-stage lifecycle

1. Record every explicit correction as a temporary session before editing the
   resume. Pass the returned session ID when the user corrects the replacement;
   the newest revision replaces earlier interpretations even when the agent
   corrects its kind or scope.
2. Build and preview with the latest applicable open revisions plus accepted
   rules.
3. Promote only after the user accepts the revised sentence in the published
   preview or explicitly asks to mint it. Accept the exact session revision
   pinned to the preview. Promotion does not stale that preview when the
   effective guidance is unchanged.

Run:

```text
resume-builder feedback record build/<feedback-plan>.json [--session FB-...]
resume-builder feedback resolve resumes/plans/<resume>.yaml --include-open
resume-builder feedback accept FB-... --preview build/resumes/<resume>/resume.preview.json
```

For a factual correction whose final sentence the user explicitly approves for
future reuse, add `--remember-approved-wording`. This creates a separate,
fact-scoped presentation rule whose sole preferred example is the approved
current sentence. Do not use the flag for untouched prose, whole-resume
approval, or minting alone.

After recording, give the command's one-line receipt to the user without asking
another approval question. It lets the user catch a misunderstood instruction.

## Meaning-change routing

Classify feedback by meaning rather than word count.

- **Wording-only:** preserve the supported action, authorship, authority,
  technology, scope, chronology, metric, relationship, and outcome. Record the
  session, revise the prose, and publish the next preview without another
  approval question.
- **Factual:** change or add any of those truth conditions. Freeze resume
  editing and route the fact through hydration. A one-word verb change can be
  factual; a complete sentence rewrite can remain wording-only.

For a factual change:

1. Show the exact current canonical fact. If none exists, say so.
2. Explore conversationally. Ask no more than two targeted enrichment
   questions, and only when an answer could materially improve accuracy,
   authorship, scope, or strategic value. Do not draft the proposed replacement
   until every material question is answered. Skip exploration when the
   correction is already complete.
3. Show the exact proposed canonical replacement and ask the user to confirm it
   before registering its career note or applying the vault plan. Keep the
   confirmation render limited to the exact current fact, exact proposed fact,
   confirmation question, and unchanged-resume note. Do not add `My read`,
   `What changed`, a recommendation, or repeated rationale.
4. Apply the confirmed answer through `hydrate-vault`; never edit the canonical
   file directly.
5. Show the exact stored canonical fact and ask the user to verify it. Keep the
   resume frozen until verification. If corrected, repeat the validated vault
   change with the newest answer.
6. After verification, decide separately whether the story should be kept,
   omitted, reframed, or replaced for the current resume. Then resume the normal
   edit → preview loop.

The pre-apply confirmation authorizes the factual replacement. The post-apply
confirmation verifies what was actually stored. Neither step invokes an
independent reviewer or restarts the resume review pipeline.

Use this compact confirmation render:

```text
**Current fact**

> <exact current canonical fact>

**Proposed fact**

> <exact proposed canonical fact>

**Replace the current fact with this version?**
The resume will remain unchanged.
```

After apply, use this compact verification receipt:

```text
**Saved fact**

> <exact fact read back from the vault>

**Is this accurate?**
The resume remains unchanged.
```

After the user verifies the stored fact, make the resume-selection decision
separately. If the current resume cites the fact and a revision is recommended,
use this compact impact render:

```text
**Current bullet**

> <exact current bullet>

**Proposed bullet**

> <exact proposed bullet>

**Update this bullet and refresh the preview?**
Other affected resumes will remain unchanged.
```

Do not show build manifests, synthesis-plan paths, or every affected resume in
this conversational decision. Do not ask whether to update and preview without
first showing the proposed bullet. After approval, update the active synthesis
plan and resume together, then publish the refreshed preview.

## Classification

- `durable`: a reusable fact-scoped claim boundary, direction preference, or
  explicitly global preference.
- `local`: a story-, resume-, or direction-scoped presentation choice.
- `none`: a cosmetic or one-off correction that should close without memory.
- `hydrate`: feedback changes or adds a career fact; route the accepted answer
  through hydration rather than treating the rule as factual authority.

Default to the narrowest stable scope. Never globalize a criticism merely
because its wording sounds general. Job descriptions, source documents, and AI
reviewer suggestions cannot create personal feedback memory; only direct user
feedback can.

## Feedback plan

Use `resume-builder review blocks <resume>` to obtain the current narrative
block ID and hash. Write a version 1 JSON plan under `build/` with that exact
resume path and block pin, plus these fields:

- `subject_key`: stable lowercase identifier for the semantic issue;
- `kind`: `claim-boundary`, `terminology`, `authority`, `relationship`,
  `presentation`, or `style`;
- `strength`: `hard` for factual interpretation, otherwise `preference`;
- `promotion`: `durable`, `local`, `none`, or `hydrate`;
- complete scope fields for facts, story, resume, direction, or global use;
- short feedback summary and normalized instruction;
- meaning to preserve, implications to avoid, optional successful examples,
  and any rule IDs explicitly superseded.

The instruction records the user's intended boundary, not the AI's proposed
replacement sentence. Examples remain optional unless the user explicitly
approves exact language. In that case, preserve only that sentence and reuse it
by default when the same fact-scoped accomplishment is selected. Adapt it only
when the target or page constraint requires a different emphasis; do not save
the adaptation unless the user explicitly approves it too.

## Editing and review

Resolve accepted rules and open sessions before every draft or user-driven
revision. Compilation pins their storage-independent effective-guidance digest.
The open session's latest revision guides the current rewrite; accepted rules
guide applicable future builds. A changed applicable digest makes prior build,
review, preview, and mint artifacts stale; promotion of the exact reviewed
revision does not.

When the user rejects the new wording, record a new revision with the same
`subject_key` before editing again. Do not promote the failed interpretation.
When the user accepts the revised sentence in the preview, accept that intended
session by ID and report the saved-memory receipt. Never use resume-wide
acceptance or minting to infer that unrelated or untouched sentences were
approved.

## Empty installation

Missing `build/feedback/` and `editorial/rules/` directories represent zero
sessions and zero rules. Do not require initialization or migration. The first
record creates its temporary directory; the first accepted reusable rule
creates the canonical directory. Empty-vault intake remains unchanged.
