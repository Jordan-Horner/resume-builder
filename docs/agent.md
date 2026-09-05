# Private career agent

Resume Builder's agent is an optional, bounded interface over existing career
workflows. It does not replace the deterministic scheduler, canonical vault,
application history, review gates, or notification outbox.

## Architecture

The agent is separated across three boundaries from its first release:

1. A `ModelAdapter` receives normalized turns and tools. The initial adapter
   uses PydanticAI with OpenRouter; application code does not import OpenRouter
   request or response types.
2. A `CommunicationAdapter` receives normalized inbound and outbound messages.
   Console turns and a private, allowlisted Telegram channel use the same agent
   service without changing provider or tool code.
3. `AgentTool` exposes one explicitly named application capability. The first
   toolset is read-only and returns only content-limited scheduler status and
   sanitized new-job summaries.

SQLite and the private workspace remain authoritative. Model conversation is
not a source of career facts, application state, approvals, or schedule state.

## Implementation cycles

### Cycle 1 — bounded local foundation

- PydanticAI/OpenRouter model adapter
- provider and channel-neutral contracts
- strict secret-free configuration
- zero-data-retention and data-collection-denied routing defaults
- per-turn request, tool, token, and cost limits
- console adapter and one-turn CLI
- read-only scheduler and new-job tools

### Cycle 2 — structured screening validation

- provider-neutral structured model requests validated by Pydantic
- separate deterministic eligibility and semantic career-fit results
- first-class `worthwhile_stretch` outcomes for credible, non-blocking gaps
- explicit two-sided evidence before a condition becomes hard-ineligible
- versioned fictional evaluation profiles that never become runtime defaults
- content-hash cache in generated SQLite state outside Git
- direct payload preview and explicit permission before a new provider call
- fictional discovery-recall fixtures with no candidate-specific defaults
- local resume evidence extraction into direct, adjacent, and capability concepts
- bounded, inactive discovery drafts that cannot alter scheduled searches
- no activation of seeded discovery until live recall and request-volume gates pass

### Cycle 3 — conversational screening and saved decisions

- deterministic command routing for screen, dismiss, and save actions after the
  direct screening path passes evaluation
- model-tier selection by task rather than by channel
- separately tested tool selection and screening quality
- durable, auditable shortlist decisions outside model conversation
- target capture only after the user chooses to pursue a job
- explicit approval handoff to existing review and mint workflows

### Cycle 4 — communication adapter and controlled notifications

- a private Telegram channel behind the existing channel contract
- long-polling controls, update deduplication, and sender/chat allowlists
- approved proactive-notification templates
- narrow application-status and resume-workflow tools
- approval policy based on consequence, not provider confidence alone

The Telegram channel and bounded conversation history are implemented. Its tool
surface remains read-only. Proactive templates, application/resume mutation
tools, and consequence-based approval buttons remain future work.

### Cycle 5 — application preparation

- prepare application answers and artifact packages
- immutable audit records for every proposed action
- per-site adapters and rate limits
- explicit approval before external submission until reliability is proven

## Configure the first cycle

Install optional agent dependencies and create the private configuration:

```bash
python -m pip install -e ".[agent]"
resume-builder agent init
```

The generated `agent/config.yml` contains model names, privacy controls, and
limits, but no credential. Put the OpenRouter key only in the environment:

```bash
export OPENROUTER_API_KEY="..."
resume-builder agent doctor
resume-builder agent ask "What new jobs are ready to review?"
```

Use `--model-tier reasoning` or `--model-tier writing` only when the task needs
the stronger configured model. The default `fast` tier minimizes routine cost.

## Configure private Telegram conversations

Install the optional channel dependency, then run the personal setup wizard:

```bash
python -m pip install -e ".[telegram]"
resume-builder agent telegram-setup
```

The wizard opens Telegram Web. Scan Telegram Web's QR code with the Telegram app
on your phone, create a private bot through the official `@BotFather`, and copy
the returned token directly into the wizard's concealed prompt. The wizard
validates the bot without displaying its token and stores it outside both Git
repositories in an owner-only credential file. Setting
`RESUME_BUILDER_TELEGRAM_BOT_TOKEN` still overrides that file for containers and
other managed deployments.

The wizard then displays a one-use pairing QR code. Scan it and tap **Start**.
Telegram returns the random pairing value with the private message, allowing the
wizard to configure the numeric user and chat allowlists automatically. Stale
messages, group messages, and messages without the matching value cannot claim
the pairing. The value expires when setup completes or times out.

Setup and the running service use one exclusive lock, so setup refuses to run
while polling is active instead of racing with live messages. Advanced users
can still inspect pending identities without printing message text:

```bash
resume-builder agent telegram-ids
```

The resulting secret-free `agent/config.yml` channel resembles:

```yaml
schema_version: 2

channels:
  telegram:
    enabled: true
    token_env: RESUME_BUILDER_TELEGRAM_BOT_TOKEN
    allowed_user_ids: [123456789]
    allowed_chat_ids: [123456789]
    private_chats_only: true
    history_max_turns: 20
```

Keep the existing provider, model, routing, and limit sections unchanged. An
empty allowlist denies every sender. Usernames are never authorization keys.
Validate the local settings and remote bot identity, then start long polling:

```bash
resume-builder agent doctor --channel telegram
resume-builder agent serve --channel telegram
```

Telegram conversation history is non-authoritative and stored in an external
owner-only `agent-state.sqlite`, never in the workspace or engine repository.
Inbound turns and reply progress are captured there before processing. The
service resumes unfinished turns and unsent reply chunks at startup and every
30 seconds; a turn enters model history only after its full reply is delivered.
`/new` and `/forget` remove both retained history and queued payloads for the
current chat. `/status` asks the existing read-only agent for automation health.
Unauthorized messages are ignored before any model request. Operational logs
contain neither message bodies nor credentials.

For Docker, enable the opt-in Compose profile after setting the token and the
existing workspace, runtime, and OpenRouter variables:

```bash
docker compose --profile telegram up -d telegram-agent
```

The Discord webhook remains a separate one-way notification sink; it does not
share conversational state with Telegram.

The initial private-workspace wizard now offers optional Telegram, Gmail, and
Discord setup guidance. Existing users can reopen the same guide with:

```bash
resume-builder onboard integrations
```

OpenRouter account-level prompt logging should remain disabled. Its API-key
budget should also be configured as a second hard boundary outside Resume
Builder's per-turn limit.

## Prove screening before conversational routing

The deterministic command is the first screening interface so a model's tool
selection cannot be confused with screening quality:

```bash
# Shows the complete instructions and bounded packet; makes no provider call.
resume-builder agent screen <job-id> --preview-payload

# Sends that packet to the configured provider and caches the validated result.
resume-builder agent screen <job-id> --confirm-send-private-data

# Reuses an unchanged local result without another provider call.
resume-builder agent screen <job-id>

# Deliberately pays for a new result and therefore requires confirmation again.
resume-builder agent screen <job-id> --refresh --confirm-send-private-data
```

Eligibility has four constraint states: `satisfied`, `violated`, `unknown`, and
`not_configured`. Only an explicit required constraint in the candidate profile
plus contradictory explicit posting evidence can establish hard ineligibility.
Missing salary or sponsorship language stays unknown. Skill, tooling, domain,
title, and years-of-experience gaps belong to career fit and may produce a
positive `worthwhile_stretch` result.

Optional fields under `screening_profile` in `job-search/preferences.yml`
declare sponsorship needs, held clearances or licenses, willingness to obtain a
clearance, evidence-backed capabilities, and whether the existing work-mode,
location, and minimum-salary filters are `required` or `preferred`. Unset fields
remain unknown. Nothing from the fictional test profiles is loaded at runtime.
Onsite and hybrid roles use `accepted_location_terms`. Setting
`screening_profile.remote_location_terms: []` allows remote roles independently;
supplying terms restricts remote eligibility to those areas, while omitting the
field preserves the legacy shared-location behavior.

## Screen a complete new-job queue

The batch command reuses the same per-job `ScreeningResult`; it does not create
a second category vocabulary:

```bash
# Local only: reuse cached/deterministic results and expose unscreened jobs.
resume-builder agent screen-new

# Explicitly authorize bounded provider-backed screening for this run.
resume-builder agent screen-new --confirm-send-private-data
```

The local-only form also works before `agent init`; without a configured model
name it cannot reuse model-specific cache entries, but it still records
deterministic outcomes and every unscreened job without contacting a provider.

`job-search/new-job-screens.json` contains two deliberately different views.
`jobs` preserves the source's newest-first order and includes every job.
`suggested_order` contains every active job ID exactly once, ordered by the
existing recommendation and then confidence. A high-confidence weak fit remains
below a low-confidence strong fit; confidence describes certainty, not value.
Provider failures, exhausted budgets, and missing authorization remain visible
as `failed` or `unscreened`. Only a durable application disposition removes a
job from the active view.

`shadow_personalized_order` is a third, evaluation-only view. It contains every
active job exactly once and cannot affect `suggested_order`, notifications, or
visibility. Its explainable score may use explicit preference matches,
structured semantic fit, and title similarity to previously applied-to jobs as
positive evidence. Ignored jobs and reasonless `not_interested` dispositions
are never learned as negative rules. A configurable exploration fraction
interleaves lower-ranked jobs so shadow evaluation can reveal useful
opportunities that personalization would otherwise push down.

Explicit preference changes use the deterministic `resume-builder preferences`
service. An agent may translate a clear instruction into validated `set`,
`add`, and `remove` operations, but it must present the returned impact preview
and confirmation hash instead of editing YAML directly. The service rechecks
local jobs only: it cannot start collection, call a model, change application
dispositions, or delete inventory. Ignored jobs remain neutral.

Configure only the safe shadow behavior in `job-search/preferences.yml`:

```yaml
personalization:
  enabled: true
  mode: shadow
  exploration_fraction: 0.15
```

After a complete refresh, `resume-builder jobs compare-providers` creates a
same-window LinkedIn/Indeed report under `job-search/`. The refresh manifest
pins hashes of both search configuration and preferences. The report uses
canonical job identities, separates shared from unique provider contributions,
and counts useful unique jobs only when a completed semantic screen is
available. It does not contact either provider or claim exhaustive recall.

Each uncached eligible job is a separate bounded provider request. The command
will not exceed the lower of `--max-provider-jobs` and
`agent/config.yml`'s `limits.max_requests`. Its summary records provider
attempts and total reported cost without storing credentials or unvalidated
provider responses.

## Continue unified onboarding

Fresh workspaces register at least one resume or career source first. Once
source evidence exists, `resume-builder onboard` offers optional,
resumable job-search setup. It reads all registered source snapshots, deduplicates
identical content, proposes recent, related, and earlier search directions, and
collects only eligibility, location, and optional compensation preferences.

The default terminal form is interactive. Use `--json` for the structured
`user_handoff` and answer envelope consumed by an agent. Setup state and
preferences remain in the private workspace. Resume source bodies are not copied
into setup state or logs.

Saving setup creates an inactive portfolio and leaves `search.yml` disabled.
`resume-builder onboard preview-activation` returns the exact confirmation hash;
`resume-builder onboard activate --confirm <hash>` enables the portfolio without
running a scan. The scheduler waits until its next configured run.

## Create a cold-start discovery portfolio

The lower-level agent command can propose a broad first search portfolio from one general resume
without treating resume history as user preference. Preview the bounded packet,
then explicitly allow the configured provider call:

```bash
resume-builder agent discovery-plan \
  --resume resumes/baselines/<resume>.md \
  --preview-payload
resume-builder agent discovery-plan \
  --resume resumes/baselines/<resume>.md \
  --confirm-send-private-data
```

Use `--local-only` to omit model-generated adjacent titles. The generated JSON
records each query's lane, evidence, source, reason, stable ID, and enabled
state. Preview and local-only modes require neither an agent configuration nor
credentials. Provider generation is cached by the resume evidence, model,
instructions, and policy; rerunning an unchanged plan reuses that private cache.
Use `--refresh --confirm-send-private-data` only to deliberately regenerate it.

The command refuses to replace an existing editable portfolio. Use `--force`
only after reviewing the current draft. The portfolio remains
`draft-review-required`; the command neither edits the active job-search
configuration nor starts a scan.

## Review and activate discovery

Validate and edit the draft before activation:

```bash
resume-builder agent discovery-show \
  --portfolio build/job-search/cold-start-portfolio.json
resume-builder agent discovery-edit \
  --portfolio build/job-search/cold-start-portfolio.json \
  --disable <query-id>
resume-builder agent discovery-edit \
  --portfolio build/job-search/cold-start-portfolio.json \
  --add "Incident Operations Engineer" \
  --lane adjacent_title
```

Activation is a two-step local operation. First preview the exact diff:

```bash
resume-builder agent discovery-activate \
  --portfolio build/job-search/cold-start-portfolio.json \
  --search-config job-search/config/search.yml \
  --backup build/job-search/search-before-discovery.yml \
  --record build/job-search/discovery-activation.json
```

Rerun with `--confirm <hash>` to apply it. Existing manual families, location,
work modes, provider settings, request delays, and result limits are preserved.
Managed discovery families from an earlier activation are replaced rather than
duplicated. Capability combinations run only as commercial-provider queries;
direct ATS boards retain strict title-family admission.

Activation writes the exact previous configuration and a hash-pinned record but
does not start a scan. Preview rollback with:

```bash
resume-builder agent discovery-rollback \
  --record build/job-search/discovery-activation.json
```

Rollback refuses to overwrite a search configuration changed after activation.
Use the printed rollback hash with `--confirm` only after reviewing the record.

## Current safety boundary

The agent cannot edit resumes, mutate applications, send email, run a scan, or
apply for a job. It can create, review, and explicitly activate a discovery
portfolio. Normal conversation
can inspect content-free automation status and a sanitized subset of newly
discovered jobs. The direct screen command can
send one explicitly previewable private packet only when the user provides the
confirmation flag. Its generated result is advisory and cannot update inventory.
Later mutations must be introduced as separate tools with explicit validation
and audit behavior.
