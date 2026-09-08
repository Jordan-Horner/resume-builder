# Job Puller

Job Puller is Resume Builder's reusable local inventory package. It collects job
postings into a durable SQLite inventory. It does not modify resumes, submit
applications, run a server, or publish data. Resume Builder adds a separate,
candidate-aware orchestration layer for cheap prescreening and deeper screening.

## Boundaries

- Local execution through either the CLI or Resume Builder's native automation service.
- No separate repository, telemetry, hosted service, or inbound web server.
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

The personal files live under `workspace/job-search/`. New Resume Builder
workspaces receive neutral preferences and an inactive collector configuration.
ATS board identities are private, locally observed data. They are learned from
direct application links already present in inventory or from an authenticated
browser-capture CSV; the public package does not download or bundle a third-party
board list.
After career sources have been hydrated, continue the unified setup:

```bash
resume-builder onboard
```

The wizard accepts multiple registered resumes and source snapshots, keeps old
roles unsearched by default, and saves an inactive discovery portfolio. Preview
and confirm activation separately; neither setup action starts a scrape. The
public files under `config/job-puller/` remain advanced reference examples.

Search configuration describes reusable title families rather than provider query syntax. Each family can be
enabled independently. `titles` are sent to providers and also admitted by the local title gate. Optional
`title_aliases` widen the local gate without spending another provider request, while `excluded_titles` override a
match to keep adjacent categories outside the family. All three are phrase rules rather than regular expressions.
Keep personal choices such as companies, salary, and acceptable seniority in `preferences.yml`; family exclusions
should describe the reusable role boundary.

Local location matching treats United States, United States of America, US, USA,
U.S., and U.S.A. as the same explicit country. Prescreening, screening, and portal
location searches share whole-token matching; US does not match Australia or
Russia. This is not geocoding: a city without a country is not automatically
classified as American. Original posting text and saved preference terms remain
unchanged. Provider search-location parameters are unchanged.

Use `resume-builder preferences show` to inspect those personal settings. Use
`preferences propose` with a structured `set`, `add`, or `remove` request to
preview a change against the existing local inventory, then confirm the emitted
hash with `preferences apply`. This cannot delete inventory, start a provider
scan, or call an AI model. It updates screening preferences only; future search
query changes remain behind the separate discovery activation workflow.
Use `preferred_job_attributes` and `avoided_job_attributes` for explicit,
plain-language characteristics such as production ownership or phone-first
support. Exact posting matches refine deterministic recommendation ranking and
preference fit in quick screens; they never establish candidate qualifications
or hard eligibility.

A role-bound capability family can set one transport-neutral `provider_query`,
`commercial_admission: query_result`, and `commercial_only: true`. This allows
a commercial title-and-skill search only when the imported resume ties those
literal capabilities to the same role. It does not create standalone skill
searches or widen direct ATS-board admission. Ordinary manually configured
families retain strict title matching by default.

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
resume-builder jobs resolve-sources
resume-builder jobs reclassify-work-modes
resume-builder jobs reclassify-work-modes --apply
```

`jobs reclassify-work-modes` deterministically previews commercial-board observations whose
legacy Remote flag conflicts with explicit hybrid or onsite posting language. `--apply` updates
the observation evidence and the canonical mode when that observation is the preferred source.
It does not call an AI model, refetch providers, or reinterpret optional, conditional, future,
interview-only, travel-only, or technical uses of hybrid and onsite terms.

Use `jobs new` for recurring discovery. It snapshots every canonical job ID in
the database, refreshes the selected providers, then resolves newly seen
LinkedIn jobs missing work mode, location, or salary against public first-party ATS APIs before writing
the shortlist. Only active canonical jobs that did not exist before that
refresh are included. Existing, updated, reopened, and cross-source duplicate
jobs are not new. The command
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

`jobs shortlist` also creates `job-search/jobs-review.csv`, containing every job
without a durable application disposition in newest-first order. Configure title
terms, company terms, accepted and excluded location terms, unknown-location
handling, work modes, minimum salary, and optional senior-title role families in
the private `job-search/preferences.yml`. These settings produce visible warnings;
they do not rank, hide, or delete collected inventory. Incomplete descriptions
also remain visible and are marked for follow-up.
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
Container deployments may override the default LinkedIn target without modifying the private workspace by setting
`JOB_PULLER_LINKEDIN_RESULTS_WANTED`. Normal validation still applies, including the `max_cards_scanned` ceiling.

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

LinkedIn's logged-out detail response usually does not expose the external Apply
destination. If an external destination is present, it is validated hop by hop.
For authenticated pages, export `job_id,captured_url` rows and import them into
the private inventory and board registry:

```bash
resume-builder jobs boards import-capture linkedin-ats-capture.csv
```

Resolve first-party copies of active LinkedIn jobs missing work mode, location, or salary:

```bash
resume-builder jobs resolve-sources             # read-only dry run
resume-builder jobs resolve-sources --apply     # attach verified ATS observations
resume-builder jobs resolve-sources --limit 50
resume-builder jobs resolve-sources --provider workday
resume-builder jobs resolve-sources --provider workday --max-requests 100
```

The resolver first checks direct ATS observations already stored by the normal
provider refresh. It removes local matches before loading or querying the board
catalog. Remaining jobs prefer the private board registry learned from captured
Apply destinations, followed by optional private catalog snapshots and bounded
company-slug probes. Candidate requests are prioritized by provenance; duplicate
provider/board endpoints are fetched only once. Workday uses exact employer-tenant
and title searches, then requests job details only for exact-title hits. Its CXS
detail fields—not the generic posting page—supply the location and work mode.
Requests are bounded and concurrent; no browser, account, cookie, or paid proxy
service is required. When Bright Data is enabled under **Settings → Integrations**,
scheduled refreshes send only newly seen LinkedIn jobs that remain unresolved after
the free pass through that optional provider, subject to its configured per-refresh
record cap. **Enrich missing details now** processes the existing unresolved backlog
without rescanning normal job sources. Completed attempts are cached for 30 days;
temporary failures retry after one day, and exact-ID misses retry after seven days.
For LinkedIn-only jobs at least 14 days old, the first exact-ID miss marks the job
possibly closed and a second later miss closes it; any later successful result
reopens it. Each paid batch checks at most one job per
company and prioritizes jobs missing both work mode and salary. A captured ATS board
is saved to the private registry and checked against
the company's other unresolved jobs before another paid lookup. A free-path match must have the
same normalized title, at least 85% three-word description coverage, a unique
best candidate, and an explicit ATS work mode. The ATS observation becomes the
canonical display source while the LinkedIn observation remains as provenance.
Ambiguous or weak matches do not write anything.

This resolution step runs automatically inside `jobs new` whenever LinkedIn was
part of the refresh. Automatic runs apply verified matches before shortlist
generation, prioritize LinkedIn observations seen during that refresh, then use
remaining capacity to drain the historical unresolved backlog. They record their
result under `source_resolution` in the latest-refresh manifest. The manual
command remains useful for read-only audits and explicit backfills.
Resolution failure is visible in the manifest but does not change provider
refresh success.

`--probe-missing` additionally tries a bounded set of safe company-derived
Greenhouse, Ashby, and Lever board IDs when the catalog has no useful entry.
Workday tenants are never guessed. It is opt-in for manual runs. Automatic runs
enable this fallback for at most 8
missing companies per refresh, within a hard 40-request ceiling. Configure the
bounds with the optional
`source_resolution` mapping in `search.yml`:

```yaml
source_resolution:
  enabled: true
  max_targets_per_refresh: 100
  max_board_requests_per_refresh: 40
  max_probe_companies: 8
  workers: 12
  catalog_cache_hours: 24 # retained for configuration compatibility
```

Private registry lookup remains the efficient bulk path. Workday candidates are
searched by exact title and each distinct tenant/site endpoint is retained until
verified, including duplicate site names hosted in different datacenters.

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

Audit a small, attributed batch from the Feashliaa community ATS catalog without
adding jobs or enabling boards:

```bash
uv run job-puller boards audit-catalog
uv run job-puller boards audit-catalog --provider greenhouse --limit-per-provider 25
```

The audit supports only the existing Greenhouse, Lever, Ashby, and Workday
adapters. It resolves and records the exact upstream commit, validates identifiers
onto fixed ATS hosts, continues from a private cursor, and writes a JSON filter
waterfall under `job-search/build/`. The report identifies healthy boards that
currently produce matching jobs as promotion-ready, but promotion remains a
separate reviewed action. The external company lists are CC BY-NC 4.0; the audit
downloads them only for explicit private use and they are not bundled with this
package.

After review, set `enabled: true` on the boards worth monitoring. A whole ATS board is filtered locally through the
same enabled title families and incremental cutoff used by commercial discovery, preventing unrelated company
openings from flooding inventory. Accepted work modes are reported as recommendation-profile matches rather than
destructive ingestion gates. Boards may carry reusable tags such as `faang-plus`; tags are
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
