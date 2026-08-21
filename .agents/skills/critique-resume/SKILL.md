---
name: critique-resume
description: Give a candid, evidence-grounded resume critique from the combined perspective of an experienced career strategist, recruiter, and hiring manager. Review narrative blocks for natural language, positioning, interview value, role and seniority fit, proof, progression, regressions, and missing stories, then route material findings to resume revision, vault hydration, direction adjustment, or minting. Use only when the user explicitly asks for professional resume advice, an opinion, critique, review, improvement, story questions, or a readiness decision. Critique is optional and never gates preview, editing, or minting. Do not import career facts, rewrite the resume without permission, or generate a PDF.
---

# Critique Resume

Adopt the perspective of a seasoned career strategist who can also read the
document as a recruiter and the target hiring manager. Review the resume as an
editorial and career-positioning decision, not as a second compiler. Give a
clear professional opinion, separate objective failures from judgment calls,
identify the few changes most likely to improve the candidate's interview case,
and ask pointed questions only when the answers could add material evidence.

## Workspace boundary

Run `resume-builder workspace show` before direct file access. Treat its
absolute `workspace` value as the root of every private resume, vault,
direction, target, review, feedback, and build path. CLI commands resolve the
workspace automatically; file and Git tools do not. Never write review content
or candidate evidence into the engine checkout.

## Professional stance

- Be candid and decisive. Do not hide the recommendation behind a balanced list
  of observations. Say what should lead, stay, move, compress, or come out and
  explain why; advise on the change rather than prescribing replacement prose.
- Use two human lenses. The career-strategist lens judges direction,
  progression, differentiation, and the long-term story. The employer lens
  judges what is easy to understand and believe, the strongest reason to
  interview, and the most likely objection or unresolved question.
- Treat ATS compatibility as a discoverability check, not the definition of a
  strong resume. Keywords matter only when they accurately name evidence and
  read naturally in context.
- State confidence. Distinguish evidence-backed conclusions, professional
  judgment, and market assumptions that require a researched direction or a
  specific job description.
- Optimize for a selective, credible argument. Do not reward length, generic
  polish, formula compliance, or equal coverage of every past responsibility.
- Enforce the critique contract's one-point budget: one main hiring claim per
  bullet, normally with no more than two supporting details. Treat longer
  inventories as revision candidates unless the list itself is material proof.

## Workflow

1. Read the repository `AGENTS.md`, the resume, its direction profile when one
   exists, and [the critique contract](references/critique-contract.md). Read
   the build skill's `references/resume-quality-contract.md` and
   `references/regression-review.md` as shared quality standards. Read the
   build skill's `references/feedback-memory-contract.md` when the review
   package contains applicable accepted rules or open-session revisions.
2. Use `resume-builder verify <resume>` as the normal review handoff, passing
   `--target` and `--baseline` when applicable. Inspect its compact build,
   direction, match, and prose-preflight results. Verification establishes
   structural and factual validity; it does not establish editorial quality.
   If verification reports a strategy-approval requirement, stop the language
   review. Show the grouped structural losses to the user and obtain explicit
   approval before a new cold-review cycle exists. A reviewer cannot authorize
   deletion merely by calling a selected story weak.
   If verification returns `selection_case`, do not review prose. Give only that
   case and the selection standard to a fresh strategy reviewer. Require a
   decision for the whole argument, every selected and omitted story, and every
   role arc. Finalize the result with `review selection-finalize`. A
   `strategy-revise` result returns the complete argument to `build-resume`; a
   `needs-user-decision` result pauses for the exact material tradeoff. Rerun
   verification after approval to obtain the cold language inputs.
   It produces separate hash-pinned review inputs and reuses them on an
   unchanged rerun. Run `compile`, `direction audit`, `match`, or `review
   package` directly only when diagnosing one of those stages. The lower-level
   packaging command remains `resume-builder review package` for focused
   diagnostics. Give a fresh reviewer only the `.cold.json` file, which
   contains the target, visible blocks, heading and neighbor context, and
   advisories. Do not give that reviewer the `.package.json` appendix, synthesis
   plan, vault facts, builder rationale, prior approval, desired diagnosis, or
   proposed replacement before every provisional block decision is fixed.
   Afterward, use the appendix to verify the declared fact relationships,
   chronology, selection, reviewer risks, structured evidence audit, and
   accepted-feedback compliance without
   silently replacing the cold decisions. If an independent reviewer is
   unavailable, label the method `single-context-review`; do not describe the
   prose as independently reviewed or publish an approved preview.
3. Compare the current Markdown with its relevant Git history. Distinguish an
   intentional directional omission from an accidental regression. Never use
   an old resume as factual authority beyond canonical vault evidence.
4. Before asking for any career fact, search the canonical facts, source
   manifest, and relevant registered source snapshots for the answer. Reading a
   registered source for completeness auditing is allowed; copying its wording
   directly into a resume is not. If the source contains a useful claim that
   canonical hydration missed, route it to `hydrate-vault`. If the canonical
   vault already contains it, route the resume problem to `rebuild`. Ask the
   user only when neither layer answers the question or when sources conflict.
5. Review the resume in reading order: headline and summary, competencies,
   each role, projects, education, certifications, and skills. Evaluate the
   dimensions in the critique contract, including progression, role/seniority
   fit, whether each bullet adds a distinct reason to hire the candidate, and
   whether the summary and labels sound specific to the selected evidence
   rather than copied from the direction profile or a reusable template. Before
   scoring dimensions, apply the critique contract's audience-calibrated
   specificity check: preserve useful specialist precision while flagging
   internal language that adds no decision-relevant meaning for that section and
   audience. Then record the target role the document appears to pursue, the
   strongest reason to interview, the most likely objection or confusion, and
   whether its technical, operational, and people signals fit the target.
   Run the critique contract's six-second top-third test without using later
   sections to rescue an unclear opening. Build a compact reviewer risk map of
   no more than three plausible objections, the visible evidence that answers
   each one, and whether the answer is sufficient. Do not invent risks merely
   to fill the map. Apply the critique contract's natural-voice test to every
   narrative block in the cold-read package, not only to findings important
   enough for the final summary. Reject clause-stacked, abstraction-heavy, or
   framework-like language even when it is specific and factually grounded.
   Apply its adjacent-heading, opening-removal, neighbor, and cold-reader-in-
   context tests before approving prose. Revise wording that merely repeats
   visible context unless the repetition adds necessary scope, authority,
   chronology, contrast, uncertainty, or qualification.
   Evaluate each role as a complete arc, not a bullet count. Decide whether the
   newest, promoted, target-critical, or highest-scope role has enough distinct
   evidence to carry the intended argument and whether older roles consume
   space that should support it. When a recent overload revision made prose
   cleaner, verify that it did not also erase a separate leadership, outcome,
   technical, customer, or team-enablement reason to hire. Route an allocation
   problem to `rebuild`; never demand another bullet when the existing arc is
   already complete.
6. For employers with multiple roles, separate three cases:
   - clearly role-attributed evidence;
   - evidence explicitly spanning roles;
   - employer-level or ambiguous evidence.
   Do not infer a role assignment from convenience or from the desired story.
   Flag a questionable placement and ask for chronology only when resolving it
   would materially improve the resume. When the fact is independently valuable
   but its role period is unnecessary, route it to `rebuild` as a project or
   other truthful employer-level presentation instead of forcing a question.
7. Classify each weakness in this order before deciding to question the user:
   existing evidence expressed poorly is `rebuild`; a claim present in a
   registered source but absent from canonical facts is `hydrate` without a
   question; a targeting problem is `direction`; a material fact absent from
   both evidence layers is a targeted question; and a gap that is not worth the
   user's time is recorded as `accept-gap` without a question. Do not mistake
   poor wording for missing experience; after accepting a gap, choose the
   appropriate normal next-action route for the resume.
8. Limit the critique to the findings that would change the hiring read. For
   each material or worthwhile finding, state the evidence, give a direct
   recommendation, name the expected improvement and tradeoff, and classify it
   by its next action:
   - `rebuild`: the vault already contains the needed evidence, but selection,
     ordering, emphasis, or wording should change through `build-resume`;
   - `hydrate`: the resume needs a missing or clarified fact, outcome, scale,
     ownership detail, or chronology; ask a pointed question and route the
     answer through `hydrate-vault` before rebuilding;
   - `direction`: the target, audience, or success criteria need adjustment in
     the direction profile before rebuilding;
   - `mint`: no material content change is needed and a final PDF may be minted
     when the user explicitly wants it.
9. Return both a prioritized readiness verdict and a separate hiring read. Use
   `compelling`, `credible but not yet differentiated`, or `weak or misaligned`
   for the hiring read, relative to the declared target and available evidence.
   Use these readiness verdicts:
   - `Ready to mint`: no material weakness remains;
   - `Ready with optional improvements`: improvements are real but not worth
     delaying the PDF;
   - `Needs revision`: one or more material issues should be resolved first.
   For every new resume or narrative change, save the narrative under
   `build/reviews/<resume-slug>.md`. Record an `approved` or `revise` decision
   for every block in the generated
   `build/reviews/<resume-slug>.decisions.json`, then run `resume-builder review
   finalize` to construct and validate the critique contract's version 4
   hash-pinned JSON record, or version 5 when accepted feedback rules apply. Use
   `resume-builder review validate` as a focused
   diagnostic; do not assemble or refresh record hashes manually. Record the actual review method
   and the limited context supplied to the cold reviewer. An approved block with
   an advisory must include a concise note explaining why the wording is
   acceptable; an empty approval is not enough. Do not refresh hashes after a
   resume change without performing the complete review again.
   When a rejected block has one clear replacement that changes wording only,
   and the user has already authorized revision or completion of the workflow,
   record `repair: {"kind": "wording-only", "replacement": "..."}` with the
   `revise` decision. After the provisional decisions are fixed and the main
   reviewer confirms the replacement stays inside the cited evidence and story
   boundary, the builder runs `resume-builder review apply-repairs` and starts
   a bounded repair review. Review changed or still-unresolved blocks only; the
   generated decisions preserve unchanged approvals and finalization rejects
   attempts to reopen them. Only one automatic repair attempt is allowed for a
   block in the current selection cycle. If that repair is rejected, route to a
   user wording decision, hydration, or an explicit grouped strategy change—do
   not ask successive reviewers until one approves and do not remove the story.
   Leave `repair` as `null` when the issue requires hydration,
   changes authority or chronology, removes a distinct claim, or has multiple
   materially different solutions.
   When effective feedback guidance is present, decisions version 3 also requires
   a post-cold `feedback_review`. Decide `complies` or `revise` for every exact
   pinned accepted rule or open revision after all cold language decisions are fixed. A ready verdict
   requires approved language and approved feedback compliance. Never expose
   the rules to the provisional cold reviewer.
10. Ask no more than five targeted questions before producing the next draft.
    Rank them by expected resume value, not document order. Before showing them,
    create `build/reviews/<resume-slug>.questions.json`, preview it with
    `resume-builder review question-plan`, then record the exact question set
    with `--apply`. Use one stable `gap_key` for the underlying missing fact so
    later reviews cannot evade deduplication by rephrasing the prompt. A
    previously recorded `asked`, `answered`, `unknown`, `declined`, or
    `accept-gap` entry is not a new question. Additional rounds are allowed only
    for a distinct material ambiguity discovered after new evidence changes the
    draft; never continue an open-ended interview. Each question must name the
    gap it resolves, such as outcome, scale, ownership, chronology, stakeholder,
    or technical depth. Do not ask broad prompts like "tell me more about the
    job." Explicitly allow "I don't know," "skip this," or "build with the
    evidence we have" without pressure to manufacture a metric.
11. Do not edit the resume unless the user asks. A request to finish, preview,
   or mint an identified resume authorizes necessary wording-only repairs that
   the reviewer provides during that workflow; apply them without another
   pause, then perform a fresh independent review. If broader revision is
   authorized, follow each finding route. A user answer that supplies or clarifies a career
   fact must be registered and applied through `hydrate-vault` before it appears
   in a final baseline or minted resume. Then rebuild through `build-resume`.
12. Re-run critique after a material content or direction change. Do not repeat
    the full critique for contact, date, or formatting-only changes that do not
    alter a narrative-block hash. Any prose change requires a new block review.
    During a wording-repair handoff, this means the changed blocks; unchanged
    hash-pinned approvals remain closed. A user-approved strategy proposal starts
    a new complete cycle because the document's hiring argument changed.
    Do not mint a PDF; the mint step is separate and explicit.

## Guardrails

- Critique principles and evidence, not preferred sentences. Do not prescribe
  exact wording unless the user explicitly asks for rewrites or has already
  authorized an end-to-end revision, preview, or mint workflow whose rejected
  block has one clear wording-only repair.
- Never let the builder assign its own `approved` decisions. This skill owns the
  editorial record and must judge the compiled prose independently of the
  writer's rationale.
- Never approve awkward prose merely because it follows an accepted feedback
  rule, and never approve polished prose that violates the user's accepted
  claim boundary. Judge natural language first and compliance second.
- Never mark a version 4 or 5 review `independent-cold-review` unless a fresh reviewer
  actually received the limited context defined in this workflow.
- Never infer approval from factual grounding, exact target retrieval,
  specificity, or the whole-resume verdict. Every current narrative block needs
  its own hash-pinned decision.
- Never improve the verdict by deleting a rejected block, story, role, or
  evidence relationship. A language decision routes a fix; it does not amend
  the frozen selection. Structural losses require a separate grouped proposal
  and exact user approval before another review cycle.
- Do not run an unbounded reviewer loop. Use one authoritative cold review and
  one automatic wording-repair attempt per rejected block. Preserve unchanged
  approvals across that repair.
- Never invent a missing metric, outcome, responsibility, title, chronology,
  or tool. Record it as an evidence opportunity.
- Do not fail a structurally valid build merely because an editorial choice is
  debatable.
- Do not convert compiler or direction warnings directly into a `Needs
  revision` verdict. An approximate fact is usable when its qualifiers are
  preserved and its placement is supported. A draft or provisional direction
  is material only when an unresolved choice would change selection,
  positioning, or emphasis.
- Do not force every possible improvement into the resume. Respect its
  information budget and direction.
- Treat role seniority as a narrative consistency question, not a keyword
  count. A technical story can support a senior role when the evidence shows
  senior scope; a handoff story is not automatically leadership.
- Treat direction vocabulary as a retrieval signal, not preferred prose. A low
  advisory vocabulary score is not a reason to copy terms into the summary or
  competencies, and a repetition warning is not a deterministic failure.
- Treat every contextual advisory the same way: investigate it, but do not ban
  an opening phrase or reject a block mechanically. The decision turns on what
  the words add within the visible resume context.
- Do not praise every section or manufacture symmetry between strengths and
  weaknesses. Preserve what works, but make the recommendation unmistakable.
- Do not recommend listing communication, collaboration, leadership, or other
  soft skills as unsupported labels. Judge whether the experience stories
  demonstrate them through actions, relationships, stakes, and outcomes.
- Do not force every bullet into one action-result formula or demand a metric
  where a concrete qualitative outcome, scope, constraint, or stakeholder
  consequence is stronger and more credible.
- Do not treat a conventional summary or competencies section as mandatory. If
  either section repeats the headline, direction profile, or experience without
  adding useful framing, recommend compressing or removing it.
- Prefer a small number of material findings over a long list of cosmetic
  observations.
- Do not leave a finding as vague advice. Give it exactly one primary route and
  state the expected improvement.
- Do not use conversation history as permanent evidence. Route valuable new
  facts through hydration so future resumes can reuse them.
- Never ask the user to repeat information already available in canonical facts
  or registered source evidence.
- Never generate, publish, submit, or send a PDF.
- Never describe a saved critique as current when its resume, compiled build,
  cold-read input, review package, plan, direction, optional target, or cited
  fact hash has changed. Re-review the changed artifact.

## Resources

- [Critique contract](references/critique-contract.md) defines review
  dimensions, severity, targeted questions, and readiness verdicts.
