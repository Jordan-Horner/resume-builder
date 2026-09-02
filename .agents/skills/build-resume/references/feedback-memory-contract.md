# Conversational feedback memory contract

Use feedback memory when the user asks to edit, replace, shorten, remove, or
reframe visible resume prose, or says that wording is inaccurate, unnatural, or
otherwise undesirable.

## Semantic drafting gate

Interpret the user's meaning before treating feedback as authorization to edit.
Use three semantic states:

- **Exploring:** the user rejects, doubts, questions, or remains tentative about
  the whole sentence or its meaning. Keep all candidate wording in conversation.
  Identify the intended hiring message and offer three to five materially
  different alternatives. Do not record feedback, write files, compile, invoke
  reviewers, or refresh the preview.
- **Needs factual clarification:** the requested wording may change authorship,
  authority, technology, scope, chronology, metric, relationship, or outcome,
  and the canonical evidence does not settle the boundary. Inspect evidence
  read-only and ask only the narrow factual question needed to continue. Do not
  use a stronger alternative until its claim is supported.
- **Ready to apply:** the user unambiguously selects or supplies the wording to
  use. A clear reference to one offered alternative is authorization; proceed
  without another confirmation. Only now record the feedback session and begin the
  edit, language-review, and preview workflow.

Store the selected candidate as data, not as a fourth workflow state. Semantic
intent controls the transition; do not depend on a hardcoded list of rejection
or approval phrases. Mixed or tentative signals remain `exploring`, including a
complete user-written sentence that they still describe as unfinished. When in
doubt, continue conversational drafting without repository actions.

Before offering alternatives, perform a read-only factual preflight against the
current canonical fact and supported claim boundary. This protects verbs and
scope without turning ordinary wording dissatisfaction into a hydration or
review workflow. Alternatives must differ in emphasis or sentence strategy,
not merely rotate synonyms.

## Persisted lifecycle

1. After the semantic drafting gate reaches `ready to apply`, record the chosen
   correction as a temporary session before editing the resume. Pass the
   returned session ID when the user later corrects the applied replacement;
   the newest revision replaces earlier interpretations even when the agent
   corrects its kind or scope.
2. Build and preview with the latest applicable open revisions plus accepted
   rules. Open revisions may carry the exact selected wording so the active
   edit remains stable.
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

Ordinary acceptance promotes semantic guidance and removes sentence examples
from the durable rule. Add `--remember-approved-wording` only when the user
explicitly asks to reuse the exact accepted narrative block in future work.
For a factual correction, this creates a separate fact-scoped presentation rule
whose sole preferred example is the approved current sentence. For other
reusable feedback, it preserves the exact accepted block in that rule. Do not
infer exact-wording authorization from `looks good`, whole-resume approval,
silence, or minting alone.

After recording, give the command's one-line receipt to the user without asking
another approval question. It lets the user catch a misunderstood instruction.
Never issue this receipt while candidate wording is still being explored.

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
5. Compare the stored canonical fact with the exact replacement the user
   approved. When they match, factual approval is complete: show a concise
   `Saved` receipt without repeating the fact or asking another verification
   question. If they differ or a new conflict appears, show the discrepancy,
   keep the resume frozen, and resolve it through another validated vault change.
6. After a matching save, decide separately whether the story should be kept,
   omitted, reframed, or replaced for the current resume. Then resume the normal
   edit → preview loop.

The pre-apply confirmation authorizes the factual replacement. The post-apply
read-back is an internal equality check, not a second user approval step. It
invokes no independent reviewer and does not restart the resume review pipeline.

Use this compact confirmation render:

```text
**Current fact**

> <exact current canonical fact>

**Proposed fact**

> <exact proposed canonical fact>

**Replace the current fact with this version?**
The resume will remain unchanged.
```

After a matching apply, use this compact receipt:

```text
**Saved**
<fact title> now matches the version you approved.
The resume remains unchanged.
```

Do not repeat the stored fact or ask another verification question when the
read-back matches. After the matching save, make the resume-selection decision
separately. If the current resume cites the fact and a revision is recommended,
use this compact impact render. Copy the company and role exactly from the
affected bullet's visible resume placement heading; never infer, normalize,
promote, or otherwise rename the role. For a non-experience narrative block,
use its exact visible section heading instead:

```text
### **<Company> — <Role>**

**Current bullet**

> <exact current bullet>

**Proposed bullet**

> <exact proposed bullet>

**Update this bullet and refresh the preview?**
Other affected resumes will remain unchanged.
```

Do not show build manifests, synthesis-plan paths, or every affected resume in
this conversational decision. Do not ask whether to update and preview without
first showing the exact affected placement or section heading and the proposed
bullet. After approval, update the active synthesis plan and resume together,
then publish the refreshed preview.

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
replacement sentence. Examples in an open session stabilize the active
revision, but ordinary acceptance strips them before creating durable guidance.
Preserve exact wording only when the user separately and explicitly requests
future reuse. In that case, preserve only the accepted narrative block and
reuse it within its approved scope. Adapt it only when the target or page
constraint requires a different emphasis; do not save the adaptation unless the
user explicitly approves it too.

Treat an approved sentence without exact-reuse authorization as the protected
incumbent in the resume source, not as a prompt example. Future regeneration
must not silently replace that incumbent. When the user asks for a fresh
challenger, run `resume-builder feedback resolve <plan> --semantic-only` and
draft from the resulting constraints, synthesis strategy, target, and canonical
evidence without using preferred sentence examples. Compare the challenger
with the incumbent and update the resume only after the user selects it.

## Editing and review

Resolve accepted rules and open sessions before every draft or user-driven
revision. Compilation pins their storage-independent effective-guidance digest.
The open session's latest revision guides the current rewrite; accepted rules
guide applicable future builds. A changed applicable digest makes prior build,
review, preview, and mint artifacts stale; promotion of the exact reviewed
revision does not.

Preferred examples are drafting aids rather than semantic compliance authority,
so they are excluded from the effective-guidance digest. The resume source and
review pins protect the selected incumbent. Instructions, preservation
requirements, and avoidance constraints remain part of the digest and stale a
build when their meaning changes.

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
