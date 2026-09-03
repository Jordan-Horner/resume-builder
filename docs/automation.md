# Scheduled job and application automation

Resume Builder can run job discovery and Gmail application reconciliation on a
low-noise schedule. The scheduler is a native engine capability; Docker Compose
is the supported always-on deployment wrapper. No web server or inbound port is
required.

## What runs automatically

- Job discovery runs at one or more local times each day. Each run refreshes
  enabled providers, identifies canonical jobs that are genuinely new, records
  deterministic warnings, and alerts for every new job without a durable
  application disposition. Alerts and saved review output preserve newest-first
  order; relevance heuristics do not suppress opportunities.
- Gmail reconciliation runs on a lower-priority interval. It uses the existing
  read-only Gmail policy and applies only confident lifecycle updates.
- Empty scans do not notify. A durable outbox prevents duplicate notifications
  and retries delivery after a restart.
- Each scanner retries two times after a transient failure. Three consecutive
  failures create a generic health alert and defer to the task's normal schedule.

The service never submits an application, sends or replies to Gmail, replays
ambiguous messages automatically, commits Git changes, or pushes a private
workspace.

## Configure

From the private workspace, create the default configuration:

```bash
resume-builder automation init --timezone America/New_York
resume-builder automation doctor
```

The generated `automation/config.yml` defaults to one 8:00 AM job scan and one
Gmail scan every four hours. Add a second job time when desired:

```yaml
jobs:
  enabled: true
  times: ["08:00", "17:00"]
  run_on_start: true
  limit: 50
  semantic_screening:
    # Enabling this authorizes scheduled bounded posting/profile provider calls.
    enabled: false
    max_jobs_per_run: 6
```

Semantic screening is disabled by default. Enabling it is explicit ongoing
authorization for scheduled runs to send bounded posting and candidate-profile
packets to the provider configured in `agent/config.yml`. The per-run maximum is
also capped by the agent request limit. Cached and deterministically ineligible
results do not consume that allowance.

A screening failure is recorded as unresolved and does not fail the completed
collection run. This prevents the scheduler from repeating provider discovery
merely because the model provider was unavailable. Notifications report
recommended, unresolved, additional, and total job counts; every job remains in
the full queue.

The schedule uses the declared IANA timezone, including daylight-saving changes.
`run_on_start` makes first deployment immediately test the corresponding scanner.
Set it to `false` to wait for the first scheduled time or interval.

Change common settings without editing YAML:

```bash
resume-builder automation configure --job-time 08:00 --job-time 17:00
resume-builder automation configure --gmail-hours 6
resume-builder automation configure --notifications discord --privacy summary
```

Test exactly one task without starting the service:

```bash
resume-builder automation once --task jobs
resume-builder automation once --task gmail
resume-builder automation status
```

## Notifications

Console notifications are the safe default. To use Discord, create an incoming
webhook for the destination channel, change `notifications.sink` to `discord`,
and provide the secret only through the environment:

```bash
export RESUME_BUILDER_DISCORD_WEBHOOK='https://discord.com/api/webhooks/...'
resume-builder automation doctor
```

The configuration stores only the environment-variable name. It never stores
the webhook URL. Discord URLs are restricted to the official HTTPS webhook
hosts. `privacy: summary` includes company, role, and job links; use
`privacy: counts-only` to omit those details.

Routine notifications respect the default 9:00 PM to 7:00 AM quiet period in
the generated configuration. Interview, assessment, offer, and repeated-failure
alerts are high priority and are delivered immediately. Edit or remove
`notifications.quiet_hours` to change that behavior.

The external automation database retains sanitized run summaries and a
content-limited notification outbox. The outbox may contain the same structured
company, role, and URL fields chosen for a summary notification, but never Gmail
subjects, bodies, attachments, message IDs, or job descriptions. Delivered
notifications remain as deduplication records. The database stays outside both
Git repositories.

Outbound email is intentionally not part of this release. It will be a separate
notification adapter with separate credentials so Gmail scanning can remain
`gmail.readonly`.

## Run continuously without Docker

```bash
resume-builder automation run
```

The process handles `SIGINT` and `SIGTERM`, prevents a second scheduler from
using the same automation state, and prevents overlapping job or Gmail scans.
Operational failures are recorded by category without serializing provider
responses or email content.

## Run with Docker Compose

Authorize Gmail on the host before starting the container. The runtime mount
should be the external directory that already contains `gmail-token.json` and
`gmail-state.sqlite`.

```bash
cp automation.env.example .env
# Edit the two absolute paths in .env.
docker compose build
docker compose run --rm automation automation doctor
docker compose up -d
docker compose logs -f automation
```

The container writes concise, human-readable events directly to standard output
and standard error. It immediately confirms that the scheduler started, groups
the previous and next job and Gmail scan times, and emits a quiet heartbeat every
six hours. Scanner events include a short run ID, trigger, attempt, safe stage,
duration, status, and content-free counts. Docker supplies the outer timestamp,
so the readable line does not repeat it. Set `RESUME_BUILDER_LOG_LEVEL` to
`DEBUG`, `INFO`, `WARNING`, or `ERROR`; the default is `INFO`.

Set `RESUME_BUILDER_LOG_FORMAT=json` when forwarding logs to a structured log
collector. JSON events remain versioned and include their own UTC timestamp.
The default `text` format is intended for Docker and TrueNAS log screens.

Failures contain only an exception class and sanitized local frame locations,
not exception messages. Logs never include Gmail subjects, bodies, attachments,
message IDs, OAuth credentials, webhook URLs, job descriptions, or provider
responses. The Compose configuration uses Docker's `json-file` driver with
three 10 MB files, so rotation remains the container runtime's responsibility.

Remote deployments should set `RESUME_BUILDER_IMAGE_TAG` to the exact Git commit
being built. Reusing the default `local` tag can cause a container host to reuse
an older image even after the build context changes. An immutable tag makes the
requested source version and the running image agree.

Restarting the container does not itself run either scanner. The service reads
the last completion times from the external state database, logs the resulting
schedule, and waits until a task is due. Replacing the container is therefore
safe as long as the same `/state` mount is retained.

The image runs as a non-root user, exposes no port, has a built-in health check,
and mounts rather than copies private data:

```text
private workspace  -> /workspace
external runtime   -> /state
```

The runtime directory must already exist and be writable by container user
`1000:1000`. On Docker Desktop, bind-mounted user directories are normally
mapped automatically. On native Linux, set ownership or ACLs deliberately; do
not make the token world-readable.

Stop or update the service with:

```bash
docker compose down
docker compose build --pull
docker compose up -d
```

Stopping the container does not remove the workspace, Gmail token, scan state,
inventory, applications, or automation outbox because each lives in a mounted
host directory.
