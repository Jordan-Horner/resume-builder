# Resume evidence-synthesis contract

Resume generation is not source reconstruction. Before drafting a fresh
directional baseline or performing a substantial rewrite, convert the selected
vault evidence into a deliberate story plan under
`resumes/plans/<resume-slug>.yaml`. This versioned strategy artifact is not a
candidate-fact source and not a second master resume. It is committed beside the
resume so the compiler and Git history can explain what evidence was selected,
where it was placed, and what was intentionally omitted.

## Plan versions

The loader accepts all published schema versions so existing Git history remains usable:

- **Version 1:** every planned story is required in the compiled resume.
- **Version 2:** adds `summary_job`, `summary_fact_ids`, and per-story
  `importance: core | supporting`. Core stories remain required. Supporting
  stories may be omitted when the information budget or target argument does
  not justify them; the build manifest reports every planned, used, and omitted
  story ID.
- **Version 3:** adds `target_mode`, complete `concept_fit` classification, a
  compact `reviewer_risks` map, and an explicit `presentation` decision. These
  fields make the pre-draft judgment inspectable without turning it into resume
  copy or a universal score.
- **Version 4:** adds a single `claim_focus` and a minimum `core_fact_ids` set
  to every story. The existing `fact_ids` field becomes the complete pool of
  available evidence for that story, not a checklist that must all be forced
  into the visible bullet. The build manifest records the evidence actually
  used and any unused optional fact IDs.
- **Version 5:** adds explicit `role_arcs` so story allocation is planned at the
  role level before prose compression. Each experience placement declares its
  emphasis, career-argument job, planned stories, allocation rationale, and any
  supported signals considered but intentionally omitted.
- **Version 6:** turns claim composition and page length into enforceable build
  inputs. Every story declares its visible action, object, optional scope,
  optional outcome, the relationship among combined facts, and the exact facts
  supporting each part. Every role arc separates required stories and
  dimensions from optional stories, and `page_budget` resolves either the
  direction default or an explicit user choice before drafting.

Use version 6 for new plans and substantial rewrites. Do not rename the plan or
resume with a version suffix; the schema field and Git history carry the version.

## Required plan

Record these machine-validated fields:

1. **Target argument:** the concise case the resume should make for its audience.
2. **Career progression:** the promotions, role transitions, and increasing
   scope that must remain visible.
3. **Story clusters:** groups of complementary fact IDs that together show a
   meaningful accomplishment, capability, or pattern.
4. **Bullet jobs:** the distinct contribution each proposed bullet makes to the
   argument, such as outcome, scope, technical depth, leadership, customer
   influence, or durable improvement.
5. **Priority and placement:** which role or section owns each story and why it
   deserves space for this direction.
6. **Intentional exclusions:** relevant facts considered but omitted, with a
   reason such as duplication, weak direction fit, lower evidence tier, or page
   budget.
7. **Known evidence gaps:** useful outcomes, scale, chronology, or ownership that
   the vault cannot currently support.

Version 2 also records:

8. **Summary job:** free-text planning guidance describing the distinct work the
   summary must do for this resume, not polished summary copy.
9. **Summary fact IDs:** the canonical evidence the compiled summary must cite.
10. **Story importance:** `core` for a story the argument cannot lose;
    `supporting` for useful evidence that may be omitted and reported.

Version 3 also records:

11. **Target mode:** `direct` when the candidate has directly demonstrated the
    target operating pattern, `adjacent` when the case depends on a credible
    transfer, or `exploratory` when the resume is testing a possible direction.
12. **Concept fit:** every direction concept is classified exactly once as
    `demonstrated`, `transferable`, or `unsupported`, with selected fact IDs and
    a rationale. Unsupported concepts cite no evidence.
13. **Reviewer risks:** at most three material concerns, each marked `resolved`,
    `partial`, or `unresolved`, with the evidence and planning action that shaped
    the draft. Unresolved risks remain visible in `gaps`.
14. **Presentation strategy:** whether Core Competencies has a distinct scanning
    job or should be omitted, plus which older roles should be compressed. The
    compiler enforces the competency decision; role compression remains an
    explicit editorial instruction.

Version 4 also records:

15. **Claim focus:** `claim_focus` names the one hiring message the story's
    visible bullet must deliver. It is concise planning language, not polished
    resume prose. Never copy it mechanically into the resume. Planning shorthand
    may use compressed modifiers or noun stacks; the draft must restate the
    relationship in natural, reader-facing language.
16. **Minimum evidence:** `core_fact_ids` is the smallest non-empty subset of
    the story's `fact_ids` that must support that claim. Other `fact_ids` are
    optional supporting evidence and may be used only when they materially
    improve proof, scope, outcome, or differentiation.

`core_fact_ids` requires the fact's support, not a visible summary of every
detail inside the fact. For each core fact, identify the one contribution it
makes to `claim_focus`; leave its other supported actions, systems, stages, and
qualifiers out unless they independently change the hiring read.

Version 5 also records:

17. **Role arcs:** `role_arcs` contains one allocation for every distinct
    experience placement. Each arc declares its `role_ids`, `emphasis` (`lead`,
    `supporting`, or `compressed`), `arc_focus`, ordered `story_ids`,
    `selection_rationale`, and `omitted_signals`.
18. **Omitted role signals:** each omitted signal names the supported dimension,
    its canonical `fact_ids`, and the reason it does not deserve a separate
    visible story. Unsupported aspirations belong in `gaps`, not here.

Version 6 also records:

19. **Resolved page budget:** `page_budget.max_pages` is a positive integer and
    `page_budget.source` is `direction-default` or `user`. A direction-default
    budget must equal the direction profile; changing the limit requires a plan
    change before review or minting.
20. **Structured claim boundary:** each story's `claim` declares `subject:
    candidate`, an action, object, optional scope and outcome, a composition of
    `single-fact`, `same-system`, `sequence`, or `aggregate`, and a plainspoken
    explanation of the factual relationship.
21. **Claim-part evidence:** `claim.evidence` assigns facts separately to the
    action, object, scope, and outcome. The visible block must cite exactly the
    union of those facts. Core facts cannot sit outside that boundary, and a
    `single-fact` claim can cite only one fact.
22. **Required and optional role allocation:** each arc lists
    `required_dimensions`, `required_story_ids`, and `optional_story_ids`.
    Required stories are core and must cover the declared dimensions; optional
    stories are supporting and may be omitted without making the role arc
    incomplete.

Every experience story must belong to exactly one role arc and agree with that
arc's role placement. Every progression role must appear in an arc, at least one
arc must lead the resume's argument, and arcs marked `compressed` must agree with
the presentation strategy. These are allocation-integrity checks, not minimum
or maximum bullet counts.

The plan must cite the complete evidence set used by the summary. Role-scoped
employment facts must also appear in a later resume block so the introduction
synthesizes proof instead of introducing an orphaned role claim. Organization-
scoped facts may remain summary-only when assigning them to one role would guess
at chronology. The compiler checks these conditions; it does not attempt to
judge whether the prose is persuasive.

## Pre-draft decision order

Before choosing stories, classify every direction concept as:

- **demonstrated:** direct canonical evidence supports the capability;
- **transferable:** adjacent canonical evidence supports careful positioning but
  not the full target claim; or
- **unsupported:** no canonical evidence supports the claim.

For a real posting, use the `match-job` criterion review and its `met`,
`partial`, `not_met`, and `undecidable` statuses instead of maintaining a second
classification. Never upgrade transferable or partial evidence into a direct
claim.

Select evidence in this order:

1. required target criteria when a preserved real posting exists;
2. high-priority direction concepts;
3. the strongest canonical evidence under the quality contract's hierarchy;
4. distinct contribution within the page and information budget.

Make a compact reviewer-risk map before finalizing the plan. Identify at most
three plausible doubts that would materially change the hiring read, connect
each to canonical counter-evidence or an explicit gap, and let the result change
selection or ordering only when justified. Record the map in `reviewer_risks`
and unresolved risks in `gaps`; do not turn it into resume content or invent
generic objections for symmetry.

Choose a presentation strategy after story selection. A Core Competencies
section is `include` only when it has a specific scanning job that the summary,
experience, and skills do not already perform. Otherwise choose `omit`. Record
older roles that should be compressed so chronology can remain visible without
giving every period equal space.

For version 6, resolve the page budget and allocate role arcs before drafting.
Treat the most recent,
target-relevant, promoted, or highest-scope role as a short argument: inventory
the distinct supported hiring signals it could carry, choose the signals that
best answer the target and reviewer risks, and record meaningful omissions. A
lead arc may have three stories or six; the count is correct only when each
story adds a separate reason to hire and the arc does not omit a stronger signal
merely to satisfy page density. Compress older or adjacent arcs before removing
the lead arc's strongest distinct evidence.

Use fact IDs and planning language. Do not draft polished bullet sentences in
the synthesis plan. Each experience story declares `role_ids`; each factual
resume block carries a matching `<!-- story: <story-id> -->` comment. The
compiler rejects missing core stories, mismatched evidence sets, duplicate
story use, unplanned claims, missing planned summary evidence, and role-scoped
facts placed outside their canonical roles. In version 3 it also rejects a Core
Competencies section that contradicts the recorded presentation decision. A
version 1 plan treats every story as core. Versions 2 through 5 record supporting
omissions rather than hiding them.

Versions 1 through 3 retain their exact story-evidence behavior. In versions 4
and 5,
the compiler requires every `core_fact_ids` item, rejects evidence outside the
story's `fact_ids` pool, and allows the writer to leave optional evidence out.
The synthesis audit reports the fact IDs actually selected and the optional
facts deliberately left unused. Version 5 also reports planned and used story
counts, primary jobs, and omitted signals for every role arc; omission from one
bullet never removes a fact from the vault.

Version 6 replaces aggregate evidence coincidence with a visible claim
boundary. Compilation verifies that the bullet or project uses exactly the
claim-part evidence, that its planned action, object, scope, and outcome are
actually expressed, and that authorship or authority verbs are supported by
the facts assigned to the action—not by an unrelated fact elsewhere in the
same citation list. This is structured integrity, not universal semantic
entailment; the career review still judges whether the complete sentence and
the declared relationship are truthful, natural, and persuasive.

## Composition rules

- Build bullets from story clusters, not by automatically turning every fact
  into one bullet.
- Combine facts only when they describe the same defensible story and the
  resulting statement preserves their ownership, period, and certainty.
- Treat a canonical fact as an evidence container, not a sentence or story
  boundary. One fact may contain several actions or accomplishments, while one
  strong story may draw on several facts. Sharing a fact file, role, employer,
  system, or time period is not by itself a strategic reason to combine them.
- Give every proposed story one dominant hiring claim. Additional evidence may
  join it only when it strengthens that claim as method, scope, constraint,
  reliability, or result. Separate actions can still form one story when their
  relationship is clear—for example, monitoring that made a delivered system
  operable—but the plan must express that hierarchy instead of joining
  co-equal accomplishments with an unexplained `and`.
- Keep facts separate when they demonstrate materially different capabilities
  or when combining them would obscure chronology or authorship.
- Give every bullet one primary job. Supporting details may reinforce that job,
  but a later bullet must add a different dimension to the role story.
- Choose the opening verb from the candidate contribution explicitly supported
  by the core facts. Action-verb lists may help retrieve precise language but
  never authorize stronger authorship or authority. A story whose honest lead
  is only `used`, `utilized`, or `leveraged` must identify a supported diagnosis,
  resolution, change, or result that deserves the space; otherwise omit it. Do
  not disguise weak evidence with `created`, `built`, `designed`, `owned`,
  `managed`, or `led`.
- After choosing accurate verbs one story at a time, inspect their rhythm across
  the complete role. A run of identical openings is a prompt to recover each
  story's distinct supported contribution or outcome, not permission to rotate
  synonyms or increase authority.
- In versions 4 and 5, begin with `claim_focus` and the minimum `core_fact_ids`
  set.
  Treat the remaining `fact_ids` as available evidence, not a checklist. Add an
  optional fact only when it makes the same claim more convincing; otherwise
  leave it unused and let the build manifest report the omission.
- In version 6, draft inside the structured `claim` boundary. Do not borrow an
  action from one fact, an object from another, and an outcome from a third
  merely because all appear in the same story pool. Use only the facts assigned
  to each claim part and preserve the declared relationship among them.
- Do not preserve evidence by stacking parallel lists, clauses, and technical
  inventories into one sentence. Do not solve the opposite way by turning every
  optional fact into its own bullet. Select the smallest defensible expression
  of the claim within the role's complete argument.
- Run a subtraction test after drafting: remove each clause and list item in
  turn. If the claim remains equally credible and differentiated, omit that
  detail. Treat separate inventories of what happened and where it happened as
  a strong overload signal, not as proof of technical depth.
- Follow subtraction with redistribution. When a removed action, audience,
  outcome, or leadership dimension would make a different supported hiring
  claim, return it to the role arc and decide whether it deserves its own story.
  Record a reason if it remains omitted. Do not let cleaner sentences produce a
  thinner role argument by accident.
- Apply a strategic-relationship test before prose: do the selected details
  jointly prove one stronger hiring claim, or are they merely several true
  things placed together? Keep a coherent combination, trim evidence that does
  not materially strengthen the dominant claim, and split only when the
  secondary accomplishment supplies a distinct target-relevant reason to hire
  the candidate and earns the role and page space.
- Match the supporting dimension to `primary_job`. Leadership and ownership
  bullets normally earn space through stakes, decisions, coordination, or
  outcomes—not a raw inventory of every system touched. Preserve exact technical
  breadth in a distinct technical-depth story or skills section when it is
  independently differentiating.
- One bullet cannot simultaneously have a leadership primary job and a
  technical-depth primary job. A leadership, ownership, coordination, customer,
  or outcome story must not carry a raw comma-separated technology or system
  inventory to imply hands-on credibility. Plan independently material breadth
  as a separate technical-depth story instead.
- Use `importance` to describe the story's role in the argument, not as a proxy
  for fact quality. Omitting a supporting story never deletes it from the vault
  or from Git history.
- Give the summary a resume-specific synthesis job. Do not use the field to
  store a stock sentence or force the same introduction across directions.
- Ensure every role-scoped employment fact used by the summary is demonstrated
  again later in the document. Profile, skills, and organization-scoped facts
  may establish context without mechanical repetition or guessed chronology.
- Prefer the strongest relevant evidence across the complete vault, regardless
  of which imported resume originally contained it.
- Generate fresh structure and language from canonical evidence. Do not change
  accurate terminology, product names, metrics, or technical details merely to
  appear different from a source.
- A resume is improved through stronger selection, grouping, ordering, and
  clarity—not synonym substitution.

## Pre-draft check

Do not begin resume prose until the plan shows:

- a clear target argument;
- distinct bullet jobs;
- a complete role arc for every experience placement, with lead-role allocation
  driven by distinct supported hiring signals rather than a bullet quota;
- one claim focus and a minimum supporting evidence set for every story;
- one structured action/object/scope/outcome boundary for every story;
- one dominant hiring claim per story, with an explicit strategic relationship
  for every additional action or accomplishment included in that boundary;
- supported role placement;
- visible career progression where relevant;
- use of the strongest directionally relevant evidence available across the
  vault;
- explicit treatment of meaningful omissions;
- a declared target mode and complete concept-fit classification;
- no more than three evidence-linked reviewer risks; and
- a presentation choice that gives each retained section a distinct job;
- a resolved page budget; and
- explicit required-versus-optional stories for every role arc.

If the plan cannot meet those conditions, route the gap to the direction or
hydration workflow before drafting.

Validate with `resume-builder synthesis resumes/plans/<resume-slug>.yaml`.
Compilation revalidates the plan and records its hash in the build manifest.
