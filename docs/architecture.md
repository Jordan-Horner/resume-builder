# Architecture

![Resume Builder architecture](assets/architecture.png)

Resume Builder separates durable evidence from generated presentation. The
boundary is deliberate: changing a sentence should not change the underlying
career history, and passing a structural check should not be mistaken for
editorial approval.

## Layers

1. **Sources** preserve imported resumes and notes as untrusted evidence.
2. **Canonical facts** store one versioned claim per Markdown file with source
   provenance, employment scope, and confirmation status.
3. **Directions and targets** describe the role being pursued. They guide
   selection but can never become candidate evidence.
4. **Synthesis plans** make story selection, omissions, reviewer risks, and
   evidence composition inspectable before prose is written.
5. **Resume Markdown** is the only editable presentation source. Every factual
   block cites canonical fact IDs.
6. **Language review** cold-reads every new or changed narrative block and
   reuses exact approved unchanged blocks.
7. **Hybrid routing** sends strong resumes directly to preview, competitive but
   improvable resumes through selection and hiring review, and exploratory
   resumes to an honest evidence-gap handoff.
8. **Preview** reuses the current build and language record, then publishes
   editable HTML.
9. **Editing** recompiles and rechecks changed narrative blocks before preview.
10. **Minting** treats the explicit mint request as approval of the current
   preview and adds page-budget, overflow, network, JavaScript, and
   text-extraction checks.
11. **Application history** preserves submitted-artifact pins, append-only
    outcomes, and evidence-cited answers without turning application prose into
    career evidence.
12. **Portal career views** keep imported source documents in the evidence layer and
    expose generated Resumes from canonical Markdown and build reports. The library
    shows every directional resume and only tailored
    resumes backed by a current successful mint; internal build and review status is
    not presented as document metadata. FastAPI compiles and renders the current
    canonical Markdown with the existing selected theme for a read-only portal view.
    That view omits CLI workflow notices and does not change review or mint state,
    publish a reviewed preview, or expose arbitrary workspace files.
    Job-search enrichment is automatic and role-bound: a title may receive a
    bounded provider-query refinement only when two literal skills co-occur in
    evidence for that same role. Standalone skill searches are never created, and
    manually entered titles remain title-only unless a supported relationship already
    exists. Onboarding marks every uploaded career document
    as a resume in the same source manifest, while the Resumes page presents only
    directional and tailored outputs. Resume-driven role suggestions select from typed
    source entries rather than unrelated career notes. Operating-system
    metadata files are ignored during both import and generated-resume discovery.
13. **Portal resume recommendations** reuse preserved targets, direction metadata,
    and existing match reports. FastAPI selects and presents the closest supported
    resume; the browser does not score or choose one. Marking a job applied pins
    that target, resume, and match report in the existing application record when
    available, so later interview work can recover the submitted artifact.

## Local appliance boundary

The published Docker image presents one container and one portal port. A small
process supervisor keeps the FastAPI portal and independently managed job,
Gmail, and Telegram workers isolated inside that container while they share the
mounted private workspace and external runtime directory. This is a deployment
boundary, not a new source of truth: the existing CLI workflows, configuration
files, locks, and databases remain authoritative. The portal may start or stop
the job scheduler through the supervisor's container-private socket; it never
receives Docker or host control privileges.

The portal is the core health surface. An intentionally disabled scheduler is a
healthy state; an enabled but unavailable scheduler is degraded. Optional
worker failures do not deliberately make the portal unavailable. Fresh
installations create an inactive automation configuration; the user explicitly
enables recurring scraping in the portal.

## Trust boundaries

| Input | What it may influence | What it may not establish |
|---|---|---|
| Imported resume or career note | Candidate fact proposals | Canonical truth without review |
| Role research | Direction and terminology | Candidate experience |
| Job posting | Selection and match criteria | Candidate experience |
| Application answer | Retrieval of prior submitted wording | New career facts |
| Application outcome | Advisory calibration of past decisions | Automatic rubric changes or hiring probabilities |
| Language model | Drafting and judgment | Unsupported facts or authority |
| Deterministic compiler | Traceability and structural integrity | Persuasiveness or semantic truth |
| Selection reviewer | Story choice and complete hiring argument | New facts or resume prose |
| Career-professional review | Language quality and hiring read | New factual evidence or story deletion |

## Dependency shape

The package is organized around functional workflows rather than a web-service
layering model. `atomic`, `layout`, `rendering`, and `validation` provide shared
boundaries. Higher-level modules orchestrate source import, synthesis,
compilation, verification, feedback, review, matching, preview, and minting.

Dependency-neutral modules now separate canonical Markdown parsing, feedback
resolution, review schema enforcement, and synthesis models from the workflows
that write artifacts. Feedback acceptance pins the user-approved preview, while
compilation depends only on feedback resolution; neither relationship points
back toward its caller. The package import graph is therefore acyclic.
Version-11 synthesis plans also represent summary positioning as structured
strategy: hiring frame, semantic fit posture, operating-scope evidence, one
proof anchor, and body-delegated detail. The selection reviewer receives this
non-prose strategy, while the independent language and career reviews continue
to judge visible wording without builder rationale.

`review_records.py` historically owned package construction, decision
finalization, wording-only repair, record loading, freshness, and approval
enforcement. Those responsibilities now live behind a small compatibility
facade:

- `review_blocks.py` inventories narrative prose and deterministic advisories;
- `language_review.py` prepares, carries forward, finalizes, and validates the
  standalone natural-language record;
- `review_packages.py` builds cold-read and evidence-appendix artifacts;
- `review_policy.py` selects the transparent hybrid review path from the
  synthesis plan;
- `review_decisions.py` finalizes reviewer-owned decisions;
- `review_repairs.py` applies the guarded wording-only repair pass;
- `review_schema.py` strictly loads compatible record versions;
- `review_approval.py` enforces freshness for route-required or explicitly
  requested deeper critiques.

Compatibility facades keep every pre-split public symbol importable from its
original module and list it in `__all__`. A regression test pins that surface so
future extractions cannot silently break callers while moving implementation.

The same dependency direction applies to the other orchestration domains.
Job matching keeps untrusted posting validation and Markdown rendering in
separate boundary modules while its public facade owns retrieval orchestration
and CLI compatibility.
Application history is a sibling workflow rooted in the private workspace. Its
records pin targets and submitted resumes by hash, while canonical facts remain
the only permitted evidence source for answer claims. Job prescreening reads
only application-linked job IDs to suppress already-applied opportunities. The
application CLI has no arbitrary storage-root override, and advisory repost
detection derives results without replacing persisted inventory state.
The optional Gmail boundary stores OAuth credentials and content-free sync state
outside both repositories. It converts an explicit, uniquely identified
application confirmation into an append-only application event; raw message
content remains transient and ambiguous messages cannot mutate workspace state.
Workspace state and remote-privacy inspection are similarly isolated from the
mutating initialization and connection workflow.
The optional career agent follows the same dependency direction. Provider,
communication-channel, and application-tool contracts are independent. The
PydanticAI/OpenRouter adapter receives only normalized turns and explicitly
registered tools, while SQLite and the private workspace remain authoritative.
The initial agent toolset is read-only and content-limited; model conversation
cannot establish career facts, application state, or approvals.
Structured job screening follows an additional split: local deterministic
constraints own eligibility, while a provider-neutral structured model request
owns only career-fit judgment. A model cannot override a confirmed eligibility
conflict. Before that career-fit request, a candidate-independent shadow
interpreter divides the bounded posting into stable sections and local
sentence-or-list-item source units, then extracts a source-backed criterion set.
It receives public posting data only. The model cites one to three stable source
unit IDs from one section; it never supplies the displayed quote. Local validation
rejects unknown and cross-section unit references, derives the exact source text,
and requires the criterion or its retrieval terms to retain a meaningful lexical
anchor to that text. Every supplied section must be acknowledged; its criteria-bearing
disposition is derived from validated citations, and partial input is always
marked incomplete locally. Invalid interpretations cannot change the current
quick-screen result, job visibility, or inventory ordering. The cache is pinned
to posting content, schema, rubric, and model and remains outside Git; bulk
screening does not create canonical target records.

For the quick screen, a validated posting interpretation drives local retrieval
against confirmed canonical vault facts. Each resume-evaluable criterion gets
its own ranked lane, and round-robin selection prevents a broad first criterion
from consuming the evidence budget. The selector sends at most twelve short
evidence cards, records exactly which fact IDs were retrieved for each criterion,
and does not pad an empty lane with unrelated role history. Lifestyle and other
non-resume-evaluable criteria are acknowledged but never search the vault.
Search terms help discovery but never serve as candidate evidence. Positive
model findings must cite both a supplied criterion ID and fact IDs retrieved for
that criterion; unknown and cross-criterion citations are rejected. Missing
retrieval evidence remains an unknown rather than a claim that the candidate
lacks a capability. The fit response also returns exactly one structured
assessment for every resume-evaluable criterion: supported, partially supported,
transferable, unknown, or apparent gap. The server validates assessment coverage,
keeps citations inside each criterion's retrieval lane, and permits a supported
judgment only when demonstrated evidence was supplied. A required criterion with
only transferable, unknown, or apparent-gap evidence prevents a strong-fit label;
if every required criterion is unknown, the server abstains. When no required or
core criterion has a useful evidence
candidate, the service abstains locally instead of paying for the private fit
call. Screening packets and results are hash-pinned, and a cache-only local
reconstruction keeps completed criterion-driven screens addressable after the
job is reopened. Provider calls require explicit private-data confirmation, and
generated cache records remain outside Git and outside authoritative inventory
state. The portal may display this metadata, but quick screening never filters,
hides, or reorders job inventory.

The version 5 screening packet also carries the user's bounded explicit
`preferred_job_attributes` and `avoided_job_attributes`. They are sent in the
same semantic-screen request; no second model stage or preference retriever is
introduced. The result keeps preference assessments separate from résumé fit
and deterministic eligibility, requires complete assessment coverage, and
validates every cited posting excerpt locally.

The same criterion-driven screen recommends the closest active directional
resume without another provider request. The service intersects each validated
criterion judgment with the canonical fact IDs visibly cited by each resume,
then passes the resulting criterion matrix to the same gate-first classifier
used by formal CLI matching. Missing bounded retrieval remains `Unknown match`;
it is never converted into a weak resume or an assertion that the candidate
lacks experience. Resume paths and content hashes are part of the screen cache
identity, so editing or retiring a direction invalidates its old recommendation.
Applying pins the selected path, hash, and match label at that moment. A minted
same-job tailored resume still takes precedence.

Posting interpretation and private fit use separate model routes. The
candidate-independent interpretation uses the configured reasoning model and
contains only public posting text. The bounded fit request uses the configured
fast model and is the only stage that receives private candidate evidence. This
improves extraction quality independently without adding another resume-matching
call or increasing the private context sent to a provider.

Interactive manual quick screens use the already-built posting-wide evidence
packet in one provider stage. That stage has a hard 15-second wall-clock
deadline and does not retry automatically. Criterion-driven posting
interpretation remains separate from this blocking click path. Other agent
workflows keep their normal retry behavior and provider limits.

Quick-screen calibration is a separate offline boundary. Human-reviewed JSON
cases refer to the stable criterion IDs created by posting interpretation and
identify the canonical facts that are relevant to each criterion. The
`resume-builder screen-eval prepare` command deterministically samples current
screens across provider and fit into a review worksheet. Current retrieval and
model judgments are visible only as context; every human truth field begins
blank, stale schemas are excluded, and incomplete worksheets cannot be finalized.
`screen-eval finalize` emits the context-free reviewed cases, and `screen-eval`
compares saved results with those cases to report retrieval recall and precision,
assessment coverage and outcome agreement, abstention accuracy, and optional
overall-fit agreement. None of these commands calls a model, changes a screen,
or influences inventory ordering.
Project reporting uses typed artifact-status records and shared freshness
helpers while preserving its stable JSON-facing report contract.
The same compiled-build freshness check is shared by language review, career
review packaging, verification, preview, and project reporting. It covers the
resume source, template, synthesis plan, generated payload, canonical facts,
builder version, and applicable feedback guidance so one workflow cannot reuse
an artifact another workflow considers stale.
`resume_parser.py` is independent of build orchestration; feedback recording,
acceptance, and resolution are separate; synthesis models, loading, and auditing
are separate; synthesis schema primitives and direction-derived inputs are kept
outside the version-aware plan assembler; direction parsing and diagnostics are
separate; and report policy is pure workflow logic. The architecture check
rejects package cycles, forbidden reverse imports, and facade growth beyond
their reviewed budgets.

## Release invariants

- Canonical facts are never edited outside a validated change plan.
- Imported resume terms do not become portal skills until hydration creates a
  canonical vault fact. Only confirmed skill facts may be enabled as scrape-search
  signals.
- A `needs-review` fact cannot appear in visible resume prose.
- High-authority verbs must be supported by the action evidence.
- A changed resume or evidence source makes the published preview stale until
  `preview` recompiles it.
- Preview requires a current standalone natural-language record, and mint
  requires it to be approved.
- A current preview whose language verdict requires changes remains visible for
  editing but is reported as revision-required, never release-ready. Its web
  preview indexes and highlights the exact rejected narrative blocks; those
  annotations are screen-only and cannot enter the minted PDF. A template that
  cannot render the issue index fails explicitly instead of hiding the review.
- The deeper critique record is required only when hybrid routing selects it;
  it must be a current version 4 or 5 independent review that pins the current
  approved standalone language record and approved selection review.
- An explicit mint invocation approves only the exact current preview.
- PDF minting cannot bypass page-budget or extraction failures.
- Application events are append-only; corrections supersede rather than rewrite.
- Outcome reports are deterministic and advisory and never mutate match rules.

## Portal state and role policy

The portal renders authoritative backend state after job dispositions, including
both queue counts and replacement rows under the current filters. A failed refresh
can be retried without repeating a successful application or dismissal action.
The schedule editor cannot mutate configuration until its initial load succeeds,
and locks its controls while saving.

Revisiting the onboarding suggestion method is a backend-persisted transition
scoped to the current setup session. Returning to roles preserves the session,
selected roles, and later answers; additional suggestions merge without restarting
setup. Browser drafts remain presentation state, not workflow authority.

`role_policy.py` owns title validation, normalized identity, and the shared query
capacity check. `POST /api/job-search/roles/preview` validates unsaved title lists
and returns canonical titles, remaining capacity after vault skill queries, and
title constraints. Both role editors use this read-only preview before adding or
restoring titles. Save operations validate again against current state. Onboarding
accepts complete title selections and derives role decisions on the backend;
legacy decision-based answers remain supported.
