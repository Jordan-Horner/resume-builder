# Job Puller

Job Puller is a private, local-only command-line application that collects job postings into a durable SQLite inventory. It does not rank candidates, modify resumes, submit applications, run a server, or publish data.

## Boundaries

- Local manual execution only.
- No Git remote, telemetry, hosted service, or background scheduler.
- LinkedIn uses a direct logged-out guest adapter; Indeed is isolated behind `python-jobspy`.
- Greenhouse, Lever, Ashby, SmartRecruiters, and Workday use direct public board adapters.
- Resume matching remains a separate future Resume Builder concern.

## Setup

Requires Python 3.11 or newer and `uv`.

```bash
uv sync --extra dev
uv run job-puller config validate
```

The personal `config/search.yml` and everything under `data/` are ignored by Git. Start from `config/search.example.yml` on another installation.

Search configuration describes reusable title families rather than provider query syntax. Each family can be
enabled independently. LinkedIn receives one compatible Boolean query per family through its public guest jobs
surface. Indeed receives one plain query
per title because the GraphQL transport used by JobSpy does not reliably honor Indeed.com's Boolean/title syntax;
a strict local title gate removes description-only matches. Senior, lead, staff, and principal variants match a
configured base title automatically, while acronyms such as `SRE` must be listed explicitly.

## Commands

Validate configuration without scraping:

```bash
uv run job-puller config validate
```

Manually update inventory:

```bash
uv run job-puller scrape
```

Commercial-board runs print a filter waterfall showing raw results, invalid records, title rejections, remote
rejections, stale records, duplicates, and accepted observations. The same metrics are retained with the scrape
run in SQLite for later diagnostics.

Commercial providers use a default result target and may override it for specific families with
`family_results_wanted`. For LinkedIn, the target counts title- and freshness-qualified cards rather than raw
search results; `max_cards_scanned` bounds the work when search quality is poor. Queries that exhaust that scan
limit are reported as capped so coverage pressure remains visible.

Inspect inventory counts:

```bash
uv run job-puller stats
uv run job-puller stats --json
```

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

LinkedIn collection uses its logged-out search and job-detail HTML fragments without personal cookies or an
authenticated browser. Search cards are paginated with absolute offsets, deduplicated, title-gated, and
freshness-gated before full descriptions are requested. The adapter uses LinkedIn's server-side remote filter as
one signal, requires positive remote-work language, and rejects explicit hybrid or office-required contradictions
in the title, displayed location, and description. Workplace patterns are contextual so technical phrases such as
“hybrid cloud” are not treated as scheduling evidence. `remote_policy` supports `strict`, `balanced`, and `source`;
strict is the default and excludes employer-level remote language unless the role itself is verifiably remote.
Accepted observations retain the exact evidence rule, source, and matching text.

LinkedIn job details are cached by job ID and parser version for 24 hours. Search pages are never cached because
they are the rotating discovery surface. Individual malformed details are reported and skipped without hiding later
jobs, while the partial run remains unsuccessful so its checkpoint cannot advance.

## Adding direct ATS boards

Each board is explicit. Examples:

```yaml
providers:
  greenhouse:
    enabled: true
    boards:
      - id: example
        name: Example Company
  lever:
    enabled: true
    boards:
      - id: example
        name: Example Company
  ashby:
    enabled: true
    boards:
      - id: Example
        name: Example Company
  smartrecruiters:
    enabled: true
    boards:
      - id: ExampleCompany
        name: Example Company
  workday:
    enabled: true
    boards:
      - id: example-workday
        name: Example Company
        api_url: https://example.wd5.myworkdayjobs.com/wday/cxs/example/jobs/jobs
```

Branded or unusual boards may set `api_url` explicitly. Workday always requires its public CXS endpoint because tenant and site names cannot be derived safely from a display name.

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
