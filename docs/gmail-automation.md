# Gmail application confirmation automation

Resume Builder can detect explicit application confirmations without storing
email content. Gmail remains the correspondence system of record; the private
workspace receives only the resulting application and its structured event.

## Boundary

- OAuth scope: `gmail.readonly` only.
- Normal scan: messages carrying the `Resume Builder` Gmail label.
- Backfill: a narrow Gmail query for explicit application-confirmation phrases.
- Downloaded content: message headers and bounded text bodies; no attachments.
- Retained outside Git: OAuth token, mailbox history cursor, Gmail message and
  thread IDs, processing disposition, application/event IDs, and timestamps.
- Retained in the private workspace: company, role, application date, optional
  inventory job link, and an `application_confirmed` event.
- Never retained: raw body, HTML, quoted thread, signature, or attachment.

Application events store an opaque hash rather than a Gmail message ID. The
external runtime database is the only place that can associate a Gmail message
with an application event.

## Install and authorize

Install the optional official Google client dependencies:

```bash
python -m pip install -e ".[gmail]"
```

In Google Cloud, enable the Gmail API, configure an OAuth consent screen, and
create a Desktop OAuth client. Keep the downloaded client configuration outside
the engine and private workspace, then authorize once:

```bash
resume-builder gmail connect --credentials /secure/path/google-client.json
```

By default, macOS state lives under:

```text
~/Library/Application Support/Resume Builder/
```

Linux uses `$XDG_STATE_HOME/resume-builder/` or `~/.local/state/resume-builder/`.
Override locations with `RESUME_BUILDER_GMAIL_STATE` and
`RESUME_BUILDER_GMAIL_TOKEN`. The CLI refuses paths inside the engine or private
workspace.

Google classifies Gmail read access as restricted. A personal-use application
can remain private, but a test-mode external OAuth project issues short-lived
authorizations. Token failures surface as errors and require `gmail connect`
again; they are never silently ignored.

## Scan and backfill

Create a Gmail label named `Resume Builder` and use Gmail filters or manual
labeling to place likely recruiting mail there.

```bash
resume-builder gmail scan
resume-builder gmail scan --apply
```

The preview does not create runtime state or application files. `--apply`
records content-free processing state, creates or links confident applications,
and advances the Gmail history cursor. Later runs request only mailbox changes
after that cursor. If Gmail expires the cursor, the adapter performs a bounded
query recovery.

Historical discovery does not require labels:

```bash
resume-builder gmail backfill
resume-builder gmail backfill --apply
```

Messages are processed using their original Gmail timestamp. Repeated runs are
idempotent. A new classifier version may reconsider earlier ignored or ambiguous
messages, while messages that already created or linked applications remain
committed.

## Schedule regular scans

After one interactive `gmail connect`, a server timer can run the apply command
from the configured private workspace. For example, a cron entry that checks
every 15 minutes is:

```cron
*/15 * * * * cd /absolute/path/to/private-workspace && /absolute/path/to/resume-builder gmail scan --apply
```

Use absolute paths and run the timer as the same operating-system account that
owns the external token and runtime database. The command is idempotent, returns
nonzero when Gmail or local validation fails, and never sends email. Sending
digests or alerts should be a separate outbound policy so read-only mailbox
access remains isolated from notification credentials.

## Automatic policy

The initial policy automatically commits only `application_confirmed` events.
A message must contain an explicit confirmation phrase and yield both a company
and role. Known inventory jobs are linked only by exact normalized company and
title identity. A matching application within three days is linked rather than
duplicated.

Messages missing company or role are ignored without changing the tracker.
Interview, recruiter-contact, rejection, offer, reply, and calendar-invite
classification are intentionally not enabled yet. The retained mailbox/thread
identifiers and structured application-event provenance provide the foundation
for those future policies without retaining correspondence.

## Status and removal

```bash
resume-builder gmail status
resume-builder gmail disconnect
resume-builder gmail disconnect --apply
```

The removal preview reports whether external state and credentials exist.
Applying it deletes the local token and content-free runtime database. Confirmed
application events remain as application history and can be corrected through
the normal append-only supersession workflow.
