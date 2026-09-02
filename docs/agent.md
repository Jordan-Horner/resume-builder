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

### Cycle 2 — durable conversation and Telegram

- content-limited SQLite conversation/event records outside Git
- sender allowlist and replay protection
- Telegram long-polling adapter with no inbound port
- notification-outbox delivery through the same channel boundary
- job cards with stable action identifiers

### Cycle 3 — screening and resume preparation

- deterministic command routing for screen, dismiss, and save actions
- model-tier selection by task rather than by channel
- versioned evaluation cases for tool calling, screening, and prose
- target capture and read-only resume-tailoring preview preparation
- explicit approval handoff to existing review and mint workflows

### Cycle 4 — WhatsApp and controlled mutations

- Twilio or direct Meta adapter behind the same channel contract
- webhook signature verification, idempotency, and sender allowlist
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

## Current safety boundary

The first cycle cannot edit resumes, mutate applications, send email, run a
scan, or apply for a job. It can inspect content-free automation status and a
sanitized subset of newly discovered jobs. Later mutations must be introduced
as separate tools with explicit validation and audit behavior.
