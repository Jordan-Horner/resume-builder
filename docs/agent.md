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
   The console is the first adapter. Telegram and WhatsApp can be added without
   changing provider or tool code.
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

- a separately chosen text channel behind the existing channel contract
- signature verification or polling controls, idempotency, and sender allowlist
- approved proactive-notification templates
- narrow application-status and resume-workflow tools
- approval policy based on consequence, not provider confidence alone

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

## Create a cold-start discovery portfolio

The agent can propose a broad first search portfolio from one general resume
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

## Current safety boundary

The agent cannot edit resumes, mutate applications, send email, run a scan, or
apply for a job. It can create an inactive discovery draft. Normal conversation
can inspect content-free automation status and a sanitized subset of newly
discovered jobs. The direct screen command can
send one explicitly previewable private packet only when the user provides the
confirmation flag. Its generated result is advisory and cannot update inventory.
Later mutations must be introduced as separate tools with explicit validation
and audit behavior.
