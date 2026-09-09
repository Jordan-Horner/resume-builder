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

Career-vault foundations live under `resume_builder.vault`. `layout.py` owns
containment-safe canonical paths, `validation.py` enforces vault structure and
provenance, `source_import.py` registers immutable source evidence, and
`evidence.py` audits resume claims against canonical facts. The established
root modules remain compatibility facades, and the `hydrate` and `validate`
commands are unchanged. Higher-level vault operations live alongside those
foundations: `change_plans.py` applies reviewed canonical writes,
`questions.py` tracks prioritized evidence gaps, `legacy_migration.py`
converts aggregate vaults, and `schema_upgrade.py` performs versioned upgrades.
Their established root modules and CLI commands remain compatibility surfaces.

Private-workspace lifecycle code lives under `resume_builder.workspace_management`.
`state.py` discovers workspaces and inspects Git remote privacy without mutation,
`templates.py` installs the packaged workspace skeleton and built-in templates,
and `setup.py` coordinates initialization, connection, template synchronization,
and the related CLI flows. The established `workspace.py`, `workspace_state.py`,
and `workspace_templates.py` modules remain compatibility facades, and the
`init` and `workspace` commands are unchanged.

Pre-application job work lives under `resume_builder.opportunities`. That domain
turns external postings into a personalized, reviewable opportunity queue: it
owns discovery coordination, source enrichment, deterministic eligibility,
semantic screening, bounded evidence retrieval, recommendations, and preference
signals. It stops at the application boundary. Application history and Gmail
lifecycle reconciliation remain sibling workflows, while the portal, assistant,
and automation layers compose both domains. The root `jobs.py` module is a
compatibility facade for the established CLI and import surface.

Post-application history lives under `resume_builder.application_tracking`.
Its records module owns append-only application events, submitted-answer history,
resume snapshots, outcomes, and reapplication signals. Its email-classification
module contains the provider-neutral semantic decision boundary. The root
`applications.py` and `gmail_semantic.py` modules remain compatibility facades;
Gmail OAuth, mailbox scanning, and runtime state remain an integration workflow.

Role targeting lives under `resume_builder.role_profiles`. Schema validation,
terminology diagnostics, profile creation, and resume-to-direction audits share
that domain rather than appearing as unrelated root modules. The established
`directions.py`, `direction_schema.py`, and `direction_diagnostics.py` imports
remain compatibility facades, and the `direction` CLI is unchanged.

Employer-ready document output lives under `resume_builder.document_export`.
It normalizes troublesome characters before rendering, audits the minted PDF's
ATS readability, and verifies text extraction and browser layout. The root
`ats.py`, `ats_readability.py`, and `pdf_rendering.py` modules remain compatibility
facades for established imports.

Canonical resume document formats live under `resume_builder.resume_documents`.
`markdown.py` parses the editable, evidence-annotated Markdown contract without
depending on compilation or review orchestration. `html.py` validates renderer
payloads and produces safe HTML. Root `resume_parser.py` and `rendering.py`
modules preserve established imports and the `render` CLI. Template selection,
compilation, preview, verification, and minting remain separate orchestration
boundaries because they coordinate planning, reviews, or release state.
Reviewed publication workflows live under `resume_builder.publishing`.
`publishing/preview.py` owns the continuously refreshed HTML approval surface,
`publishing/verification.py` prepares hash-pinned review inputs and reports
workflow readiness, and `publishing/mint.py` releases the explicitly approved
PDF. The established `previewing.py`, `verification.py`, and `minting.py`
modules and their CLI commands remain compatible.

Generated-build metadata lives under `resume_builder.build_artifacts`.
`paths.py` owns the canonical internal output locations for each resume, while
`status.py` owns typed readiness records and validates whether compiled inputs,
outputs, evidence, templates, and feedback guidance are still current. Root
`artifact_paths.py` and `artifact_status.py` remain compatibility facades.

Project-wide readiness reporting lives under `resume_builder.project_status`.
`report.py` assembles vault, direction, resume, review, preview, mint, target,
and evaluation state into one report; `policy.py` converts that state into the
current onboarding stage and next action. Root `project_report.py` and
`report_policy.py` remain compatibility facades, and the `report` command is
unchanged.

Local portal adapters live under `resume_builder.portal`. `filters.py` applies
inventory-view filters without changing discovery configuration, `schedule.py`
and `system.py` expose scheduler controls and content-free health, and
`integrations.py` coordinates short-lived Gmail and Telegram setup sessions.
`job_sources.py` controls manual provider scans while preserving the existing
collector workflow. `career.py` presents generated and retired résumés, renders
read-only portal previews, and preserves application-linked copies during
lifecycle changes. The established `web_career.py`, `web_filters.py`,
`web_schedule.py`, `web_system.py`, `web_integrations.py`, and
`web_job_sources.py` modules remain compatibility facades; the manual-scan
worker entry point is unchanged.

The portal assistant is split by runtime responsibility within the same
package. `assistant_routes.py` owns same-origin HTTP and process supervision,
`conversation_state.py` persists portal threads and proposal state,
`resume_editing.py` applies bounded wording changes through the existing review
workflow, and `assistant_worker.py` runs isolated model turns and confirmed
proposals. The established `web_agent.py`, `web_agent_state.py`,
`web_agent_resume.py`, and `web_agent_worker.py` paths remain compatibility
facades, including the worker module entry point.

`portal/app.py` composes these portal capabilities into the local FastAPI
application and owns the dashboard server launcher. The established `web.py`
module, `resume-builder-web` command, and module entry point remain compatible.
`portal/service.py` coordinates dashboard use cases across the vault,
opportunity inventory, screening, applications, integrations, and career
library. The established `web_service.py` module remains its compatibility
facade.

Resume construction is split into two internal domains. `resume_builder.planning`
owns synthesis-plan models, schema helpers, loading, summary strategy, role
balance, and plan audits. Its loader coordinates version-aware assembly while
the `stories`, `targeting`, `presentation`, and `role_arcs` modules validate
their respective plan sections. `resume_builder.reviews` owns narrative-block
review, feedback memory, selection checks, decisions, repairs, and review
packaging.
The root `synthesis.py`, `feedback_memory.py`, and `review_records.py` modules
remain compatibility facades for established commands and public imports.

Dependency-neutral modules separate canonical Markdown parsing, feedback
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

- `reviews/blocks.py` inventories narrative prose and deterministic advisories;
- `reviews/language_review.py` prepares, carries forward, finalizes, and
  validates the standalone natural-language record;
- `reviews/packages.py` builds cold-read and evidence-appendix artifacts;
- `reviews/policy.py` selects the transparent hybrid review path from the
  synthesis plan;
- `reviews/decisions.py` finalizes reviewer-owned decisions;
- `reviews/repairs.py` applies the guarded wording-only repair pass;
- `reviews/schema.py` strictly loads compatible record versions;
- `reviews/approval.py` enforces freshness for route-required or explicitly
  requested deeper critiques.

Compatibility facades keep every pre-split public symbol importable from its
original module and list it in `__all__`. A regression test pins that surface so
future extractions cannot silently break callers while moving implementation.

The same dependency direction applies to the other orchestration domains.
Job-to-resume evidence auditing lives under `resume_builder.matching`, where
exact retrieval, semantic grading, and human-readable reporting remain separate
modules. The root `job_matching.py`, `match_grading.py`, and `job_report.py`
modules preserve existing imports, and the `match` CLI remains unchanged.
Application history is a sibling workflow rooted in the private workspace. Its
records pin targets and submitted resumes by hash, while canonical facts remain
the only permitted evidence source for answer claims. Job prescreening reads
only application-linked job IDs to suppress already-applied opportunities. The
application CLI has no arbitrary storage-root override, and advisory repost
detection derives results without replacing persisted inventory state.
The implementation lives under `resume_builder.application_tracking`: `records.py`
owns the append-only application ledger and outcome reporting, while
`email_classification.py` contains the provider-neutral semantic classifier.
The root `applications.py` and `gmail_semantic.py` modules preserve their
established import surfaces; Gmail orchestration remains a separate integration
boundary.
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
The runtime implementation lives under `resume_builder.assistant`: `runtime.py`
coordinates bounded turns, `config.py` validates secret-free configuration,
`openrouter.py` implements the model-provider adapter, `state.py` owns external
conversation state, `telegram.py` delivers messages, and `tools.py` defines the
registered tool surface. Root `agent*.py` compatibility facades preserve existing
imports and the `agent` CLI. The provider-neutral `agent_contracts.py` remains
shared infrastructure, and interactive Telegram credential setup remains a
separate integration boundary.
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
state. The portal may display this metadata, but quick screening never removes
jobs from the canonical inventory. The backend exposes three views over that same
inventory. The deterministic prescreen cheaply selects candidates for background
screening by excluding hard conflicts and requiring a saved role or interest
signal. Those candidates appear in **Recommended Jobs** immediately and remain a
backlog rather than a fixed-size shelf. Candidates are screened in deterministic
preference order until the existing per-run provider cap is reached. A strong
career-fit result with medium-or-high confidence and cited candidate evidence promotes
an otherwise eligible direct recommendation to **Hot** and
sorts it first. A locally nominated unfamiliar title may also remain recommended after a
Good or Strong fit with at least medium confidence; other completed screens return to
**All jobs**. Provider failures do not empty the deterministic backlog. **Interested jobs** contains explicit
positive decisions that have not become applications, and **All jobs** remains the
complete reviewable inventory. Marking a recommendation Interested moves it from
Recommended Jobs to Interested jobs; applying or hiding it removes it from
both active queues. Closed and duplicate hides remain neutral;
only an explicit `Not interested` hide records negative preference feedback.
Current feedback and the current screening cache are combined
at request time, so these transitions never wait for the next scheduled artifact
refresh. A decision also schedules the same bounded worker to continue screening;
the Settings portal can start that worker directly against the current inventory.
The standalone backfill rebuilds the local shortlist and never invokes LinkedIn,
Indeed, ATS resolution, or another discovery provider. Source refresh and screening
therefore have independent failure and retry boundaries. The browser only requests
and renders these backend-owned views.

An unfamiliar title may also enter screening through a conservative local adjacent-role
signal derived from confirmed vault facts. This signal only authorizes the existing
quick screen; it is not a qualification judgment. Successful screens retain the
normalized title and seniority as a private learned admission pattern, while every later
posting still receives its own fit screen. Feedback is evaluated against title,
seniority, and available screened duties: one application or two Interested decisions
preserve a pattern, while three matching rejections with no positive anchor suppress it
from recommendations and automatic screening without hiding it from All jobs.

Quick-screen provider requests contain only the bounded posting, selected
candidate-evidence cards, criterion-evidence map, and coverage flags. Explicit
preferred and avoided job attributes remain deterministic recommendation and
feedback signals; they are not reclassified by the model. Salary estimation is
also a separate, explicit public-posting-only request. This keeps the private
fit request focused on the judgment the model uniquely provides.

The quick screen can recommend the closest active directional resume without
another provider request. When a cached criterion interpretation exists, the
service intersects each validated criterion judgment with the canonical fact IDs
visibly cited by each resume and passes that matrix to the same gate-first
classifier used by formal CLI matching. A posting-wide screen instead compares
only the fact IDs the fit model cited: it names a resume only when one direction
has strictly greater cited-evidence overlap than every other active direction.
It does not invent a winner on ties or zero overlap. Instead, it preserves the
vault-backed decision as actionable guidance: multiple matches when top resumes
tie, needs tailoring when cited vault facts do not appear in a current resume,
build a resume when no active direction exists, or not enough evidence when the
screen cited no facts. Resume paths and content hashes are part of the screen
cache identity, so editing or retiring a direction invalidates its old
recommendation. Applying pins the selected path, hash, and match label at that
moment. A minted same-job tailored resume still takes precedence.

Posting interpretation and private fit use separate model routes when deeper
analysis requests an interpretation. The candidate-independent interpretation
contains only public posting text. Normal queue triage uses the configured fast
fit model in one provider call and never waits for that deeper stage.

Interactive manual quick screens use the already-built posting-wide evidence
packet in one provider stage and do not retry automatically. The portal queues the existing
screen and returns immediately, exposes queued/running/failed status separately,
and polls one authoritative status endpoint while the job remains open. That same
endpoint recovers a completed result from the shared cache when no live process
state exists. Closing the job does not cancel the analysis.
Queued portal and scheduled screens have a 25-second provider deadline. The
blocking CLI command uses a shorter 15-second deadline.
Criterion-driven posting
interpretation remains separate from this manual path. Other agent
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
