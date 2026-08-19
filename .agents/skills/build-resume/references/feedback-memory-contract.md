# Conversational feedback memory contract

Use feedback memory when the user asks to edit, replace, shorten, remove, or
reframe visible resume prose, or says that wording is inaccurate, unnatural, or
otherwise undesirable.

## Two-stage lifecycle

1. Record every explicit correction as a temporary session before editing the
   resume. Pass the returned session ID when the user corrects the replacement;
   the newest revision replaces earlier interpretations even when the agent
   corrects its kind or scope.
2. Build and review with the latest applicable open revisions plus accepted
   rules. Keep both out of the independent cold read, then require a separate
   compliance decision before preview.
3. Promote only after the user accepts that reviewed preview or explicitly asks
   to mint it. Accept the exact session revision pinned to the preview. Promotion
   does not stale that preview when the effective guidance is unchanged.

Run:

```text
resume-builder feedback record build/<feedback-plan>.json [--session FB-...]
resume-builder feedback resolve resumes/plans/<resume>.yaml --include-open
resume-builder feedback accept FB-... --preview build/<resume>.preview.json
```

After recording, give the command's one-line receipt to the user without asking
another approval question. It lets the user catch a misunderstood instruction.

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
replacement sentence. Examples remain optional unless the user explicitly asks
to preserve exact language.

## Editing and review

Resolve accepted rules and open sessions before every draft or user-driven
revision. Compilation pins their storage-independent effective-guidance digest.
The open session's latest revision guides the current rewrite; accepted rules
guide applicable future builds. A changed applicable digest makes prior build,
review, preview, and mint artifacts stale; promotion of the exact reviewed
revision does not.

The cold career reviewer sees neither accepted rules nor open sessions. After
provisional cold decisions are fixed, the main reviewer reads the review
package's feedback-memory appendix and records `complies` or `revise` for every
applicable accepted rule and open revision. Ready verdicts require approved compliance. Natural
language can fail while rule-compliant, and polished language can fail for
violating the user's accepted boundary.

When the user rejects the new wording, record a new revision with the same
`subject_key` before editing again. Do not promote the failed interpretation.
When the user accepts the reviewed preview, accept each intended session by ID
with that preview before minting and report the saved-memory receipt. Never use
resume-wide acceptance to infer that unrelated open sessions were approved.

## Empty installation

Missing `build/feedback/` and `editorial/rules/` directories represent zero
sessions and zero rules. Do not require initialization or migration. The first
record creates its temporary directory; the first accepted reusable rule
creates the canonical directory. Empty-vault intake remains unchanged.
