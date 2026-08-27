# Job Puller

Job Puller is a private, local-only command-line application that collects job postings into a durable SQLite inventory. It does not rank candidates, modify resumes, submit applications, run a server, or publish data.

## Boundaries

- Local manual execution only.
- No Git remote, telemetry, hosted service, or background scheduler.
- LinkedIn and Indeed are isolated behind the `python-jobspy` adapter.
- Greenhouse, Lever, Ashby, SmartRecruiters, and Workday use direct public board adapters.
- Resume matching remains a separate future Resume Builder concern.

## Setup

Requires Python 3.11 or newer and `uv`.

```bash
uv sync --extra dev
uv run job-puller config validate
```

The personal `config/search.yml` and everything under `data/` are ignored by Git. Start from `config/search.example.yml` on another installation.

## Commands

Validate configuration without scraping:

```bash
uv run job-puller config validate
```

Manually update inventory:

```bash
uv run job-puller scrape
```

Inspect inventory counts:

```bash
uv run job-puller stats
uv run job-puller stats --json
```

Use `--config /absolute/path/to/search.yml` before the command to select another configuration.
An editable local installation automatically finds this project's configuration when invoked from another directory.
`JOB_PULLER_CONFIG` can set a different reusable default.

## Incremental behavior

The first successful source run requests seven days. Later runs start at that source's last successful completion time with a six-hour overlap. Observations have stable identities, so the overlap is idempotent. Failed, blocked, partial, and suspiciously empty runs do not advance checkpoints and never close jobs.

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

`data/inventory.db` separates provider observations from canonical jobs. Exact provider identity and canonical URLs merge automatically. Similarity by title alone never merges jobs. Every merge retains its observation link and reason. Direct ATS observations take preference over commercial-board copies without deleting provenance.

Original HTML, cleaned text, parser version, hashes, and extraction timestamps are preserved. Raw provider payload bodies expire after 30 days; normalized provenance remains.

## Responsible operation

Use modest result limits and manual runs. Job boards may change or restrict automated access. Job Puller does not use personal LinkedIn cookies or automate authenticated sessions. Add proxies only after measured blocking and keep credentials outside the repository.
