# Job Puller

Job Puller is Resume Builder's reusable local inventory package. It collects job
postings into a durable SQLite inventory. It does not modify resumes, submit
applications, run a server, or publish data. Resume Builder adds a separate,
candidate-aware orchestration layer for cheap prescreening and deeper screening.

## Boundaries

- Local manual execution only.
- No separate repository, telemetry, hosted service, or background scheduler.
- LinkedIn uses a direct logged-out guest adapter; Indeed is isolated behind `python-jobspy`.
- Greenhouse, Lever, Ashby, SmartRecruiters, and Workday use direct public board adapters.
- Mutable inventory and personal configuration live under the private Resume
  Builder workspace; reusable provider code lives in the public engine.

## Setup

Requires Python 3.11 or newer and `uv`.

```bash
uv sync --extra dev
uv run job-puller config validate
```

The personal files live under `workspace/job-search/`. Start from the public
examples on another installation:

```bash
mkdir -p workspace/job-search/config
cp config/job-puller/search.example.yml workspace/job-search/config/search.yml
cp config/job-puller/boards.example.yml workspace/job-search/config/boards.yml
cp config/job-puller/preferences.example.yml workspace/job-search/preferences.yml
```

Search configuration describes reusable title families rather than provider query syntax. Each family can be
enabled independently. `titles` are sent to providers and also admitted by the local title gate. Optional
`title_aliases` widen the local gate without spending another provider request, while `excluded_titles` override a
match to keep adjacent categories outside the family. All three are phrase rules rather than regular expressions.
Keep personal choices such as companies, salary, and acceptable seniority in `preferences.yml`; family exclusions
should describe the reusable role boundary.

LinkedIn receives one compatible Boolean query per family through its public guest jobs surface. Indeed receives
one plain query per `titles` entry because the GraphQL transport used by JobSpy does not reliably honor
Indeed.com's Boolean/title syntax; the local title gate removes description-only matches. Senior, lead, staff, and
principal variants match a configured base title automatically, while acronyms such as `SRE` must be listed
explicitly.

## Commands

Validate configuration without scraping:

```bash
uv run job-puller config validate
```

Manually update inventory:

```bash
uv run job-puller scrape
uv run job-puller scrape --provider greenhouse
```

From a discovered Resume Builder workspace, prefer the unified commands:

```bash
resume-builder jobs update
resume-builder jobs update --provider indeed
resume-builder jobs new
resume-builder jobs new --provider indeed
resume-builder jobs new --retry-failed
resume-builder jobs status
resume-builder jobs shortlist
resume-builder jobs screen <job-id>
resume-builder jobs verify <job-id>
```

Use `jobs new` for recurring discovery. It snapshots every canonical job ID in
the database, refreshes the selected providers, and writes a shortlist containing
only active canonical jobs that did not exist before that refresh. Existing,
updated, reopened, and cross-source duplicate jobs are not new. The command
writes `job-search/latest-refresh.json`, `job-search/new-jobs.json`, and
`job-search/new-jobs.md`. While the refresh runs, it immediately prints the
total provider count and a flushed progress line before each provider source is
queried, so slow commercial-board searches remain visibly active. An
interrupted refresh leaves an `in_progress`
manifest and the next run recovers canonical jobs created after that interrupted
run began. A provider failure produces a failed or explicitly partial result
instead of falling back to the prior shortlist.

Every provider run is stored with one typed outcome: `healthy`, `healthy-empty`,
`capped`, `partial`, `blocked`, or `failed`. Transient failures with no retained
observations receive at most one retry by default; blocked and capped sources are
not retried automatically. `jobs status` reports the latest source outcome and
consecutive problem-run count. `jobs new --retry-failed` reads the latest refresh
manifest and reruns only provider types explicitly marked retryable.

`jobs verify <job-id>` performs a conservative live-URL check. A 404 or 410 is
treated as closed only when the canonical job is backed by a configured direct
ATS source. Redirects are reported, access challenges are marked blocked, and
aggregator-only URLs remain inconclusive. `jobs screen` includes the same check
before presenting its evidence.

The provider scrape summary reports `new_observations`, which counts newly seen
provider records and must not be interpreted as newly created canonical jobs.
`jobs new` is the canonical database-delta view.

`jobs shortlist` also creates `job-search/jobs-review.csv`, containing only jobs
eligible under the current personal review filters. Configure hard title terms,
company terms, accepted and excluded location terms, unknown-location handling,
work modes, minimum salary, and optional senior-title role families in the
private `job-search/preferences.yml`.
Filtering never deletes collected inventory, so changing a preference can make
previously hidden jobs visible again without another provider request.
Prescreen reuse is invalidated when any decision-relevant inventory field changes,
including a corrected location, work mode, salary, title, company, or description.

Repeat `--provider` to update a selected group. Omitting it runs every enabled provider.

Reconcile exact provider identities after importing historical inventory:

```bash
uv run job-puller reconcile
```

Reconciliation retains every source observation and merges canonical jobs only when a verified URL alias or exact
provider requisition identity agrees.

Commercial-board runs print a filter waterfall showing raw results, invalid records, title rejections, work-mode
profile mismatches, stale records, duplicates, and accepted observations. The same metrics are retained with the scrape
run in SQLite for later diagnostics. When title rejection occurs, the summary also prints the ten most common
rejected titles so a user can distinguish provider noise from a missing family alias.

`search.accepted_work_modes` selects any combination of `remote`, `hybrid`, `onsite`, and `unknown`. The default
configuration uses `[remote]`. The former `remote_only` setting remains readable for older private configurations,
but new configurations should use the typed list. A job can expose more than one available arrangement, so the
inventory stores modes in relational tables rather than forcing every posting into a single label.
Work-mode selection guides provider-side discovery and marks profile matches; it is not an ingestion rejection.
Every valid, recent, title-matching result returned by a provider is retained so another consumer can choose a
different work-mode view without wasting an already completed provider request.

Commercial providers use a default result target and may override it for specific families with
`family_results_wanted`. For LinkedIn, the target counts title- and freshness-qualified cards rather than raw
search results; `max_cards_scanned` bounds the work when search quality is poor. Queries that exhaust that scan
limit are reported as capped so coverage pressure remains visible.

Inspect inventory counts:

```bash
uv run job-puller stats
uv run job-puller stats --json
```

Resume Builder can also derive conservative possible-repost relationships from
the canonical history:

```bash
resume-builder jobs reposts
resume-builder jobs reposts --aggregator "Example Job Board"
```

The signal requires the same normalized employer and exact title-token identity
under distinct posting identities on different dates. Concurrent openings,
shared provider identities, and configured multi-employer aggregators are
excluded. The result is advisory and never closes or dismisses a job.

Use `--config /absolute/path/to/search.yml` before the command to select another configuration.
An editable local installation automatically finds this project's configuration when invoked from another directory.
`JOB_PULLER_CONFIG` can set a different reusable default.

## Incremental behavior

The first successful source run requests seven days. Later runs start at that source's last successful completion
time with a six-hour overlap. LinkedIn applies an additional 48-hour minimum rolling window because its guest
results rotate and are not a chronological cursor. Observations have stable identities, so overlap is idempotent.
Failed, blocked, partial, and suspiciously empty runs do not advance checkpoints and never close jobs.

Indeed cannot reliably combine its remote and freshness filters through JobSpy. Job Puller requests remote jobs
from Indeed and enforces the initial lookback or checkpoint cutoff locally. Indeed publication values have date
precision, so same-day postings remain eligible throughout that day and stable identities make the overlap safe.
A response containing older jobs but no newly eligible jobs is a healthy empty update; a response containing no
raw jobs is treated as suspicious.

Indeed occasionally geocodes Ontario, Canada as Ontario, California in a USA-scoped result and may label Canadian
compensation as USD. Job Puller corrects that conflict only when the posting independently states that candidates
should be based in Ontario and publishes a Canadian-dollar range. The original JobSpy row remains preserved as raw
provider evidence.

LinkedIn collection uses its logged-out search and job-detail HTML fragments without personal cookies or an
authenticated browser. Search cards are paginated with absolute offsets, deduplicated, title-gated, and
freshness-gated before full descriptions are requested. The adapter uses LinkedIn's server-side remote filter as
one signal and records whether role-specific remote evidence is present. Explicit hybrid or office-required
contradictions are retained as classified inventory rather than discarded. Workplace patterns are contextual so technical phrases such as
“hybrid cloud” are not treated as scheduling evidence. `remote_policy` supports `strict`, `balanced`, and `source`;
strict is the default for deciding whether a result matches the remote profile. Observations retain the exact
evidence rule, source, and matching text regardless of profile match.

LinkedIn job details are cached by job ID and parser version for 24 hours. Search pages are never cached because
they are the rotating discovery surface. Individual malformed details are reported and skipped without hiding later
jobs, while the partial run remains unsuccessful so its checkpoint cannot advance.

## Adding direct ATS boards

Discover supported boards from the direct application links already stored in inventory:

```bash
uv run job-puller boards discover
```

Discovery recognizes JazzHR/ApplyToJob, Rippling, Greenhouse, Lever, Ashby, SmartRecruiters, and Workday links.
Known Greenhouse short links are
resolved without requesting custom or untrusted redirect destinations. Results are merged into the private
`config/boards.yml` registry and new
boards are always disabled so rediscovery cannot silently expand collection. Existing enablement and tags are
preserved.

Test one vendor at a time without changing inventory:

```bash
uv run job-puller boards check --provider greenhouse
uv run job-puller boards check --provider ashby
uv run job-puller boards check --provider workday
```

After review, set `enabled: true` on the boards worth monitoring. A whole ATS board is filtered locally through the
same enabled title families, accepted work modes, and incremental cutoff used by commercial discovery, preventing
unrelated company openings from flooding inventory. Boards may carry reusable tags such as `faang-plus`; tags are
metadata for future search profiles and do not change collection behavior yet.

SmartRecruiters reads the platform's structured remote/hybrid location flags and compensation fields when present.
Title aliases are still applied locally, so profiles that want software-engineering acronyms should include forms
such as `backend SWE` alongside their descriptive titles.

Each board is explicit. Registry examples:

```yaml
schema_version: 1
providers:
  jazzhr:
    - id: example
      name: Example Company
      enabled: true
      careers_url: https://example.applytojob.com/
  rippling:
    - id: example
      name: Example Company
      enabled: true
      careers_url: https://ats.rippling.com/example/jobs
  greenhouse:
    - id: example
      name: Example Company
      enabled: true
      tags: [faang-plus]
  lever:
    - id: example
      name: Example Company
      enabled: true
  ashby:
    - id: Example
      name: Example Company
      enabled: true
  smartrecruiters:
    - id: ExampleCompany
      name: Example Company
      enabled: true
  workday:
    - id: example-workday
      name: Example Company
      enabled: true
      api_url: https://example.wd5.myworkdayjobs.com/wday/cxs/example/jobs/jobs
```

JazzHR listing pages and Rippling's public board API are title-filtered before full job details are requested, which
keeps broad company boards efficient. Rippling retrieves up to the public API's 1,000-job maximum in one listing
request and reports an error instead of silently truncating a larger board. Branded or unusual boards may set
`api_url` explicitly. Workday always requires its public CXS endpoint because tenant and site names cannot be
derived safely from a display name.

## Data model

`data/inventory.db` separates provider observations from canonical jobs. Exact provider identity and canonical URLs
merge automatically. Separate observations also merge when normalized company, normalized title, and a non-empty
description hash are all exact matches; this consolidates syndicated location variants without using fuzzy title
similarity. Every merge retains its observation link and reason. Direct ATS observations take preference over
commercial-board copies without deleting provenance.

Original HTML, cleaned text, parser version, hashes, and extraction timestamps are preserved. Raw provider payload
bodies expire after 30 days; cached LinkedIn details expire independently; normalized provenance remains.

## Responsible operation

Use modest result limits and manual runs. Job boards may change or restrict automated access. LinkedIn requests are
paced conservatively and stop on authentication, forbidden, or rate-limit responses. Job Puller does not use
personal LinkedIn cookies, automate authenticated sessions, rotate identities, or bypass challenges.
