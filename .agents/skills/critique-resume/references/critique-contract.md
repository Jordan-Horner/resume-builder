# Resume critique contract

Critique answers one question: is this resume persuasive, accurate, coherent,
and sufficiently polished for its intended audience? It does not reimplement
the compiler and it does not reward added length for its own sake.

## Professional review model

Review through three nested lenses:

1. **Career strategist:** Does the document make the right career argument from
   the candidate's strongest evidence? Does it show credible progression,
   differentiation, and a direction the candidate can defend in an interview?
2. **Recruiter or hiring manager:** During a quick human scan, what target is
   apparent, what is the strongest reason to interview, and what objection,
   ambiguity, or credibility question is most likely to stop advancement?
3. **ATS and mechanics:** Can the document be parsed and discovered for the
   right role? This lens supports human judgment; it never overrides relevance,
   authenticity, or natural language.

Give an opinion, not merely observations. Choose the recommended tradeoff when
two valid approaches compete. Label conclusions as evidence-backed,
professional judgment, or dependent on market research. Do not claim current
market expectations from general model knowledge when the direction is
provisional or no job description is available.

### Six-second top-third test

Review the headline, summary, optional competencies, and first current-role
bullet as one unit. Without using later sections to repair the opening, ask:

1. What role or problem space does this person appear to target?
2. What relevant operating pattern is demonstrated rather than merely named?
3. What proof point or differentiator earns further reading?
4. Does the opening answer, worsen, or ignore the largest credible objection?

This is a scan heuristic, not a literal timing measurement, keyword quota, or
compiler gate. A technically valid opening can still fail it by being generic,
overloaded, or focused on the wrong evidence.

### Reviewer risk map

Record no more than three plausible objections that could materially change the
hiring read. For each, cite the visible evidence that answers it, judge the
answer as `resolved`, `partially resolved`, or `unresolved`, and give one route
when action is warranted. Do not manufacture generic risks for symmetry. A risk
without canonical evidence becomes an evidence opportunity, not reassuring
summary language.

### Role-arc completeness

Read each role as a short argument rather than counting bullets. The most
recent, promoted, target-critical, or highest-scope role should receive enough
space to show its distinct supported reasons to hire, while earlier or adjacent
roles should be compressed first. There is no universal ideal count. Flag an
arc when a material leadership, outcome, technical, customer, or team-enablement
signal is absent even though canonical evidence supports it, or when several
bullets repeat one dimension while another decision-relevant dimension is lost.

After an overload cleanup, compare the role's current argument with the prior
version. Cleaner sentences are not an improvement if the edit silently removed
a different supported hiring claim. Route that loss to `rebuild`; do not add a
generic responsibility merely to increase the count.

### Narrative-block language gate

Compilation produces a draft; it never approves prose. Use `resume-builder
verify <resume>` as the normal handoff and review every block in its generated
cold-read input, including blocks that do not become material findings in the
narrative critique. Run `resume-builder review package` directly only to
diagnose that lower-level stage. A whole-resume verdict cannot substitute for
these decisions.

For each headline, summary, competency, experience bullet, project narrative,
and education description, decide `approved` or `revise` using these questions:

1. Can a target reader understand the main point on the first reading?
2. Does the block use concrete actors and actions instead of a chain of abstract
   workflow or process terms?
3. Is it carrying too many clauses, qualifiers, or lists because the writer
   tried to preserve every fact in one sentence?
4. Would a capable manager plausibly say it aloud when explaining the work?
5. Does technical language earn its place through precision or target-role
   value?

Judge the block where the candidate and employer will see it, not as an isolated
string. Use the context supplied by the cold-read package and apply all four tests:

1. **Adjacent-heading test:** Does the opening repeat the visible role, company,
   section, dates, or location without adding decision-relevant meaning?
2. **Opening-removal test:** If the opening words disappear, does the sentence
   lose supported scope, authority, chronology, contrast, uncertainty, or a
   necessary qualification? If not, remove them.
3. **Neighbor test:** Does the block duplicate the claim or setup of an adjacent
   bullet instead of contributing a distinct reason to interview the candidate?
4. **Cold-reader-in-context test:** Can a reviewer understand the actor, action,
   and value using only the visible resume context, without the writer's plan or
   internal rationale?

Record a provisional decision from that cold read before consulting synthesis
notes or builder rationale. Later evidence verification may preserve wording
when a qualifier is factually necessary, but it must not excuse contextually
redundant or unnatural prose. An advisory is a prompt for judgment, not a
deterministic failure, and no phrase—including an opening such as "As ..."—is
categorically prohibited.

When a fresh reviewer agent is available, perform this provisional language
gate from the generated `.cold.json` file and these critique standards only.
Do not disclose the `.package.json` appendix, writer's synthesis plan,
fact-grouping rationale, prior approval, suspected defect, or proposed fix.
After every provisional decision is fixed, the main agent uses the appendix to
verify evidence, relationships, chronology, and regression risk, but it may not
silently replace the cold decisions with its own approvals. A review performed
in the builder's context is a `single-context-review`, not an independent cold
review.

This is contextual judgment, not a banned-word list or a preference for casual
language. A technically dense line can pass when its structure and value are
clear. A factually correct, highly specific line must still be revised when it
sounds like a framework describing itself rather than a person explaining work.

## Review dimensions

Evaluate these dimensions with `strong`, `adequate`, or `needs work`:

1. **Direction:** The headline, summary, first bullets, and selected evidence
   reinforce one understandable target story.
2. **Proof:** Important claims have credible accomplishments, outcomes, scale,
   stakes, or concrete technical detail.
3. **Progression:** Separate roles show increasing ownership or changing scope
   without moving stories into a title merely to improve the narrative.
4. **Role and seniority fit:** Each role's bullets make sense for that role's
   documented period and level. Ambiguous chronology is identified rather than
   guessed.
5. **Distinct contribution:** Each bullet adds a new capability, quality, or
   proof point instead of restating another bullet.
   The role-level set is also complete enough for its narrative job; a strong
   supported signal is not omitted merely to keep an arbitrary bullet count.
6. **Specificity and credibility:** Language is precise about built, used,
   supported, contributed, owned, or led. Unsupported metrics and inflated
   authorship are absent.
   Communication, collaboration, leadership, and other soft skills are
   demonstrated through actions and consequences rather than asserted as
   unsupported labels.
7. **Prioritization:** The strongest and most relevant evidence appears early;
   lower-value details do not crowd out stronger proof.
8. **Scanability:** A reviewer can understand the candidate's direction,
   progression, and strongest evidence quickly. The expected page budget is
   realistic.
9. **Language fit and natural voice:** The summary has a specific job, its structure follows the
   selected evidence, and target vocabulary is used naturally. Important terms
   are calibrated to their section, evidence, and intended audience: specialist
   language retains meaningful precision or target-role value, while internal
   diagnostic, architectural, or process phrasing is translated when it adds no
   decision-relevant meaning. This is contextual judgment, not a preference for
   broad or nontechnical language. Competencies add scan value rather than
   copying concept labels or repeating proof already visible elsewhere.
10. **Regression safety:** Valuable approved content was not accidentally lost;
   intentional omissions remain available in the vault or baseline.

## Finding severity

- **Material:** Could misrepresent the candidate, obscure the target story,
  weaken seniority, hide progression, or cause a strong reviewer to reject the
  resume. Resolve before minting.
- **Worthwhile:** Would make the resume meaningfully stronger, but the current
  version remains usable.
- **Optional:** Cosmetic or preference-based. Mention only when it is unusually
  visible; do not bloat the critique with minor edits.

Machine warnings inform severity but do not determine it. A qualified
`approximate` fact may be credible resume evidence when the wording preserves
its uncertainty. A `draft` or `provisional` direction may still produce a usable
baseline; treat it as material only when its unresolved choices would change
the resume's target story or evidence selection.

Direction vocabulary and style diagnostics are advisory. Do not make a resume
less natural merely to raise vocabulary coverage, and do not fail a resume for
repetition without judging the actual reading experience and target context.

## Hiring read

Report a hiring read separately from document readiness:

- **Compelling:** The target is clear, the strongest evidence is easy to find,
  and the resume gives a credible, differentiated reason to interview.
- **Credible but not yet differentiated:** The candidate appears qualified, but
  the story, evidence selection, or prioritization does not yet separate them
  from similarly qualified applicants.
- **Weak or misaligned:** The target is unclear, the best evidence is obscured,
  or the resume makes a materially different case from the intended role.

This is a professional judgment about the document relative to its target, not
a prediction of an employer's decision or a fabricated probability.

## Finding routes

Give each material or worthwhile finding one primary route. Each finding must
also include the evidence behind the judgment, a direct recommendation, the
expected improvement, and the main tradeoff:

| Route | Use when | Next action |
|---|---|---|
| `rebuild` | The needed evidence is already canonical, but its selection, order, emphasis, or wording is weak. | Revise through `build-resume`, compile, and re-critique if material. |
| `hydrate` | A missing or ambiguous career fact prevents a stronger or more accurate resume. | Ask a pointed question, register the answer as a career-note source, apply a reviewed hydration plan, and rebuild. |
| `direction` | The target story, audience, terminology, exclusions, or success criteria are wrong or incomplete. | Update the direction profile, validate it, and rebuild. |
| `mint` | No material content or direction issue remains. | Mint only when the user explicitly requests the final PDF. |

Do not assign multiple primary routes to one finding. If hydration produces new
evidence, rebuilding is the natural next stage rather than a second route.

## Targeted evidence questions

Ask only when an answer can change selection or strengthen a material bullet.
A question is premature until canonical facts and relevant registered source
snapshots have been searched. When a registered resume already contains the
answer, classify the issue as a hydration-completeness gap rather than asking
the user to repeat it. When exact role chronology is unknown but unnecessary to
the claim, prefer a truthful project or employer-level presentation and route to
`rebuild`; do not ask merely to satisfy the current layout.

A useful question states the evidence gap and narrows the requested memory:

- outcome: what changed after the work;
- scale: users, systems, cases, incidents, regions, or frequency;
- ownership: initiated, designed, built, operated, coordinated, or approved;
- chronology: which documented role or date range contains the work;
- stakes: severity, customer impact, operational risk, or time pressure;
- collaboration: who depended on the work and what decision or handoff improved;
- technical depth: system boundary, failure mode, tooling, or constraint.

Do not imply that every bullet requires a metric. A specific operational
outcome or technical constraint can be stronger and more credible.

## Output shape

Return:

1. **Professional opinion:** a short, plainspoken recommendation stating what
   the resume currently sells, its strongest reason to interview, and its
   biggest risk.
2. **Verdict and hiring read:** Ready to mint, Ready with optional improvements,
   or Needs revision; plus compelling, credible but not yet differentiated, or
   weak or misaligned. State confidence and what context limits it.
3. **What works:** two to four strengths worth preserving; do not praise weak
   sections for balance.
4. **Reviewer risk map:** up to three hiring-read objections, their visible
   counter-evidence, resolution status, and route when action is warranted.
5. **Priority findings:** material findings first, then worthwhile findings;
   connect each to a review dimension, route, evidence, direct recommendation,
   expected improvement, and tradeoff. Keep the list selective.
6. **Targeted questions:** zero to five, only for evidence gaps that matter.
7. **Regression note:** what changed or disappeared relative to the relevant
   version, and whether it appears intentional.
8. **Next action:** summarize the routed sequence, such as hydrate → rebuild →
   critique, rebuild → critique, direction → rebuild → critique, or mint.

The critique may be delivered in conversation. Save its narrative under
`build/reviews/<resume-slug>.md`. For every new resume or narrative-content
change, complete the generated
`build/reviews/<resume-slug>.decisions.json` file, then run:

```bash
resume-builder review finalize build/reviews/<resume-slug>.decisions.json
```

The finalizer pins the current package inputs, constructs the version 4 record,
and validates complete block coverage and freshness. Do not assemble the
record's file hashes manually. The generated record has this exact shape:

```json
{
  "version": 4,
  "reviewed_at": "2026-08-17T12:00:00+00:00",
  "reviewer": {
    "method": "independent-cold-review",
    "context": "Fresh reviewer received only the generated cold-read package and critique standards before provisional decisions."
  },
  "resume": {"path": "resumes/tailored/company-role.md", "sha256": "..."},
  "plan": {"path": "resumes/plans/company-role.yaml", "sha256": "..."},
  "direction": {"path": "directions/role.md", "sha256": "..."},
  "target": {"path": "targets/company-role-date.md", "sha256": "..."},
  "build_manifest": {"path": "build/company-role.manifest.json", "sha256": "..."},
  "cold_read": {"path": "build/reviews/company-role.cold.json", "sha256": "..."},
  "review_package": {"path": "build/reviews/company-role.package.json", "sha256": "..."},
  "evidence_integrity": {
    "status": "claim-checked",
    "method": "deterministic-structured-claims",
    "structured_claims": 8
  },
  "verdict": "ready-with-optional-improvements",
  "hiring_read": "compelling",
  "findings": {"material": 0, "worthwhile": 1, "optional": 0},
  "next_action": {
    "route": "mint",
    "summary": "Mint when the user explicitly approves the draft."
  },
  "language_review": {
    "scope": "all-narrative-prose",
    "status": "approved",
    "blocks": [
      {
        "id": "experience[0].bullets[0]",
        "sha256": "...",
        "decision": "approved",
        "note": ""
      }
    ]
  }
}
```

The decisions template already populates block IDs and hashes from the exact
cold-read package; the example shows one item only to illustrate the final
record, not valid complete coverage. Use
`approved` only when every block is approved. Use
`changes-required` when one or more blocks has a `revise` decision, give each
rejected block a concise reason in `note`, and set the overall verdict to
`needs-revision`. The finalizer performs the same validation as
`resume-builder review validate`; run the latter only as an explicit diagnostic.
New decisions files use version 2 and add `repair` to every block. Use `null`
unless the rejected block has one clear replacement that changes wording only:

```json
{
  "id": "experience[0].bullets[0]",
  "sha256": "...",
  "decision": "revise",
  "note": "The sentence carries two competing inventories.",
  "repair": {
    "kind": "wording-only",
    "replacement": "One evidence-safe replacement block."
  }
}
```

When the user has already authorized revision, preview, or minting, the main
workflow validates that replacement against the evidence appendix, runs
`resume-builder review apply-repairs`, re-verifies the resume, and submits the
changed block to a fresh independent reviewer without pausing for approval of
the wording. The repair command pins the exact old block and resume hash,
preserves evidence comments, rejects multiline or structural changes, and
never carries the old approval forward. Leave `repair` null and pause only when
the issue needs a new fact, changes ownership, authority, chronology, or
substantive meaning, removes a distinct hiring claim, or presents materially
different strategic choices. Version 1 decisions remain finalizable but cannot
drive automatic repairs.
When the compiled build uses accepted rules or open feedback revisions, the generated decisions
file uses version 3. It retains version 2 wording repairs and adds a separate
`feedback_review` populated from the evidence appendix. Complete the cold
language decisions before reading these rules, then decide `complies` or
`revise` for every pinned rule. A ready verdict requires
`feedback_review.status: approved`; a violation requires `changes-required`, a
concise note, and a fresh rebuild. The resulting version 5 review pins the
effective-guidance snapshot, so later semantic changes make affected reviews
stale without invalidating unrelated resumes. Promoting the exact reviewed open
revision preserves the accepted preview.
When an advisory is present, an `approved` decision must also include a concise
note explaining the contextual judgment. The note does not need to defend
unflagged blocks. Never claim `independent-cold-review` unless the context was
actually isolated as specified above. Use `single-context-review` when it was
not; version 4 records cannot approve prose under that method.

Use `null` for `target` on a general directional review. Machine verdicts are
`ready-to-mint`, `ready-with-optional-improvements`, or `needs-revision`;
hiring reads are `compelling`, `credible-but-not-yet-differentiated`, or
`weak-or-misaligned`. The next-action route is `rebuild`, `hydrate`,
`direction`, or `mint` and records the primary routed step, not every possible
improvement. Hash the files actually reviewed. The project report marks the
review stale whenever the resume, plan, direction, optional target, compiled
build, cold-read package, evidence appendix, or any cited fact changes.
Narrative and JSON remain disposable and do not gate compilation, but preview
and minting reject missing, stale, incomplete, evidence-failed, or
language- or feedback-rejected reviews. Versions 2 through 4 remain readable
for backward compatibility. New reviews without applicable feedback use version
4; reviews with effective feedback guidance use version 5 so evidence integrity, career
review, feedback compliance, role fit, career verdict, and user approval remain
separate statuses. The
`--accept-review-risk` option may acknowledge a documented non-language fit or
evidence gap only with a written preview note after user approval; it never
bypasses a `revise` decision. Never update hashes without repeating the review.
