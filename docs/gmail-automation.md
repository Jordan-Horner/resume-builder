# Gmail application lifecycle automation

Resume Builder can detect explicit application confirmations, rejections,
recruiter outreach, interviews, assessments, and offers without storing email
content. Gmail remains the correspondence system of record; the private
workspace receives only the resulting application status and structured event.

## Boundary

- OAuth scope: `gmail.readonly` only.
- Normal scan: a narrow server-side query for recent confirmation and rejection phrases; no
  label required.
- Backfill: the same bounded application-activity query over a longer window.
- Downloaded content: message headers and bounded text bodies; no attachments.
- Retained outside Git: OAuth token, mailbox history cursor, Gmail message and
  thread IDs, an opaque sender-domain hash when the domain is company-specific,
  processing disposition, application/event IDs, and timestamps.
- Retained in the private workspace: company, role, application date, optional
  inventory job link, and structured `application_confirmed` or
  `rejection_received` events. Automated events include separate classification
  and application-match confidence values.
- Never retained: raw body, HTML, quoted thread, signature, or attachment.

Application events store an opaque hash rather than a Gmail message ID. The
external runtime database is the only place that can associate a Gmail message
with an application event.

Shared recruiting platforms such as Workday, Greenhouse, Lever, Ashby, iCIMS,
and SmartRecruiters are never treated as company-domain identity. Their domains
are not hashed or retained for matching.

## Install and authorize

Install the optional official Google client dependencies:

```bash
python -m pip install -e ".[gmail]"
```

Run the guided connection from a terminal:

```bash
resume-builder gmail connect
```

The guide explains that the integration remains local and presents one numbered
step and one direct Google Cloud link at a time. In a terminal, it renders a
compact card with a clickable terminal hyperlink, the visible URL as a fallback,
and the exact command for the next step. When output is captured by an agent or
automation, it emits the same step as structured JSON so the caller can render a
native link. Select another step explicitly, for example:

```bash
resume-builder gmail connect --step 2
```

The six steps cover project creation, enabling Gmail, configuring the app and
audience, adding an External test user, declaring `gmail.readonly`, and creating
a Desktop OAuth client. Choose Internal only when the Gmail account and Cloud
project belong to the same Google Workspace organization; personal Gmail and
accounts outside that organization use External.

Keep the downloaded client configuration outside the engine and private
workspace. Noninteractive installations and users who already have a client can
provide it directly:

```bash
resume-builder gmail connect --credentials /secure/path/google-client.json
```

The final step provides the `--credentials` command. The JSON is validated as a
Desktop client and read only to initiate OAuth; Resume Builder does not copy it.
The resulting refresh token is stored separately in the external runtime directory.

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

```bash
resume-builder gmail scan
resume-builder gmail scan --apply
resume-builder gmail scan --replay-ambiguous
```

The preview does not create runtime state or application files. `--apply`
records content-free processing state and creates or links confident applications.
Later runs repeat the bounded Gmail query and skip message IDs already processed.
An optional `--label NAME` filter enables Gmail history-cursor processing for
advanced users, but labels are not part of normal onboarding.

Previously unresolved messages are skipped during ordinary scans. After adding
or correcting application records, use `--replay-ambiguous` to reconsider only
those messages against the current tracker. Preview first, then combine it with
`--apply` only after reviewing the proposed changes.

Historical discovery does not require labels:

```bash
resume-builder gmail backfill
resume-builder gmail backfill --apply
```

Messages are sorted oldest to newest and processed using their original Gmail
timestamp, even though Gmail commonly returns newest messages first. This lets
a historical confirmation establish an application before a later rejection is
resolved. Repeated runs are idempotent, and an external lock rejects overlapping
scans. A new classifier version may reconsider earlier ignored or ambiguous
messages, while messages that already changed application history remain
committed. Corrections to committed events use the application's append-only
supersession workflow rather than silent reclassification.

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

Application confirmations require an explicit confirmation phrase plus a valid
company and role. They create an application or link one submitted within three
days. Known inventory jobs are linked only by exact normalized company and title
identity.

Rejections require strongly negative body context; the words “move forward” by
themselves are never negative. Common conditional boilerplate and quoted older
messages are removed before classification. A rejection never creates a new
application. It is committed only when it resolves uniquely by requisition,
company and role, a prior thread association, or one nonterminal application at
the identified company. Hired and withdrawn applications are not changed.
Ambiguous events remain content-free runtime dispositions for later classifier
improvements.

The job inventory reflects the application's current status, so a linked job
changes from `applied` to `rejected` when the rejection event becomes current.

Recruiter follow-ups are classified into four additional structured events:

- `recruiter_contact` for an explicit request to connect about the application;
- `interview_invited` for interview or screening scheduling;
- `assessment_invited` for a technical assessment, coding challenge, or take-home;
- `offer_received` for explicit employment-offer language.

These events never create applications. They require the same unique resolution
rules as rejections and may additionally use a prior company-specific sender-domain
association. Status transitions are monotonic: routine outreach cannot move an
application backward from a later stage, and terminal rejected, withdrawn, or
hired records are not reopened automatically. Calendar-invite parsing and outbound
notifications remain future phases.

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
