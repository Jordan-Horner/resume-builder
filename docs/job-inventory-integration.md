# Job Inventory and Resume Matching Integration

**Date:** 2026-08-27
**Status:** Implemented in Resume Builder on 2026-08-27
**Implementation:** `src/job_puller` plus `resume-builder jobs`
**Storage:** `workspace/job-search/inventory.db` in the private workspace

> This document preserves the original design investigation. The initial
> standalone repository was subsequently merged, with full Git history, into
> Resume Builder so only one public project must be maintained. The package
> boundary remains intact, but ranking orchestration now lives beside matching.

## Decision

Build a high-quality job inventory as an isolated backend package, then connect
shortlisted postings to Resume Builder through stable inventory and target
contracts. Ship both packages in one distribution while keeping mutable job data
in the private workspace.

CareerPulse is frozen for this effort. It is neither the inventory host nor a runtime dependency. Its implementation may be consulted for proven retry, enrichment, location, and source-health ideas, but no new inventory work belongs in CareerPulse and the new backend must not read CareerPulse's database.

Do not place scraper code, a mutable job database, or bulk job descriptions inside the career vault. Resume Builder continues to own:

- candidate facts and their provenance;
- reusable role directions;
- selected target-posting snapshots;
- criterion-level job matching;
- baseline and tailored resumes;
- review, preview, and minting.

The inventory system owns:

- provider adapters and board configuration;
- manual collection orchestration and rate limits;
- normalized source observations;
- canonical job identity and lifecycle;
- freshness, source health, and duplicate clusters;
- stable inventory queries and exports for later consumers.

This respects the existing repository rule that Resume Builder remains independent from any one job-search system while still allowing another tool to consume its directions and submit selected targets.

## Standalone backend boundary

Use a separate local project at `/Users/jordan/Projects/job-puller`, containing a reusable Python application exposed initially as a local CLI. It may use local Git history, but no Git remote is configured and it is not published to GitHub, a package index, or a deployment platform. Version one has no GUI, HTTP server, daemon, or scheduler. A manual `job-puller scrape` command collects, normalizes, enriches, deduplicates, and stores jobs, then prints a run summary. It does not rank jobs or run resume matching.

Start with Pydantic, SQLAlchemy/Alembic, and SQLite in WAL mode with FTS5. JobSpy is Python-native, so this avoids a cross-language wrapper. Keep orchestration, provider adapters, domain services, and persistence behind explicit interfaces so a future HTTP API can be added without moving business logic. Do not add FastAPI, Redis, a distributed queue, or a separate search server until a real consumer requires one. PostgreSQL can replace SQLite later behind the repository layer if measured concurrency requires it.

The backend owns no candidate facts or resumes. Resume Builder owns no scraper configuration or bulk inventory. Their only integration is a versioned JSON target export/import contract. Resume Builder should invoke a stable inventory CLI command or consume an exported target snapshot; it must not query the backend's internal tables directly.

## Confirmed version-one product decisions

### Operation and storage

- The inventory is a local, manually invoked CLI with no GUI or always-running service.
- `job-puller scrape` only updates inventory and reports results. Ranking and job screening belong to the later Resume Builder integration.
- One SQLite database lives at `data/inventory.db` by default. The path is configurable for other installations.
- Provider settings and search definitions live in a versioned example configuration and a user-owned local `config/search.yml`.
- Providers use global enabled/disabled switches in version one. Per-search overrides are deferred.
- No job is deleted because it disappeared. Lifecycle states include `active`, `possibly_closed`, `closed`, and `reopened`.
- A failed, blocked, partial, or suspiciously empty scrape never advances a provider checkpoint and never closes jobs.

### Provider scope

The initial supported providers are:

- LinkedIn through a pinned JobSpy adapter;
- Indeed through a pinned JobSpy adapter;
- Greenhouse;
- Lever;
- Ashby;
- SmartRecruiters;
- Workday.

Direct ATS scans initially cover boards declared in configuration and boards discovered from commercial-board results. Global reverse scanning across every known ATS tenant is deferred because it is expensive, noisy, and unnecessary for proving inventory quality.

### Incremental collection

- A provider's first successful scrape requests the preceding seven days.
- Later scrapes start from that provider's last successful checkpoint with a six-hour safety overlap.
- Checkpoints are provider-specific and advance only after a successful, non-suspicious run.
- Source IDs and observation uniqueness make overlap idempotent.
- Provider capabilities are explicit: unsupported date filters fall back to bounded retrieval plus local date normalization rather than pretending the source honored the filter.

### Content and provenance

- Incomplete cards are stored as observations and enriched during the same manual run when possible.
- Failed enrichment is recorded and retried on a later run.
- Preserve original description HTML, cleaned Markdown/text, content hash, extraction timestamp, and parser version.
- Preserve raw provider responses for 30 days for debugging. Normalized observations, hashes, and provenance remain permanently.
- When LinkedIn or Indeed resolves to an employer ATS posting, retain every source but prefer the employer posting for canonical description, status, and application URL.
- Compensation is normalized and stored but never used as an ingestion filter.
- Geographic and work-authorization restrictions are preserved as posting data, not hard-coded for one candidate.

### Duplicate policy

- Automatically merge only high-confidence matches: identical provider identity, canonical URL, employer requisition identity, or a very strong normalized company/title/requisition match.
- Similarity-only matches remain separate unless later reviewed.
- Every canonical merge retains its contributing observations and is reversible.
- Direct employer sources take precedence over commercial-board copies without erasing commercial-board provenance.

### Initial search configuration

Search configuration uses base role concepts rather than enumerating seniority variations. For example, `Production Support Engineer` also retrieves senior, lead, staff, principal, numbered, and closely normalized variants. Seniority is normalized metadata, not a separate provider query.

The initial user configuration covers these broad families:

1. Site reliability, DevOps, and cloud operations.
2. Production support and technical operations, including senior roles.
3. AI automation and AI-assisted operations.
4. Systems, configuration, and integrations.
5. Backend, API, and cloud software engineering; general frontend and full-stack searches are excluded.

The initial geographic query is United States remote work. This is configuration, not product logic: the reusable backend does not hard-code Florida eligibility, personal compensation thresholds, or candidate-specific exclusions.

### Reusability standard

- All candidate-specific choices live in local configuration, never in provider or domain code.
- Provider adapters translate into a backend-owned observation contract; downstream code never depends directly on JobSpy's DataFrame schema.
- Configuration, schema, CLI output, and target exports are versioned.
- Secrets and proxy credentials remain outside the repository.
- Every provider has fixtures, contract tests, health semantics, and an explicit capabilities declaration.
- Database migrations are forward-tested and backups are created before destructive migrations.
- Public extension points are documented so another user can add a provider without editing the ingestion core.

## Recommended system shape

```text
Direct employer ATS providers        Selected commercial boards
Greenhouse / Lever / Ashby           LinkedIn / Indeed / Glassdoor
SmartRecruiters / Workday / etc.     through a maintained adapter/library
               \                       /
                normalized observations
                         |
              canonical inventory store
                         |
            duplicate collapse + source preference
                         |
               inventory updated on disk
                         |
           later Resume Builder job screen
                         |
       shortlist -> preserve target -> match -> tailor
```

## Best ideas to combine

### From career-ops

Use these as the primary ingestion model:

- Separate provider adapters from configured company/board instances.
- Auto-detect common ATS families while permitting an explicit provider override.
- Use a common normalized posting shape across providers.
- Run HTTP/API providers with bounded concurrency.
- Keep Playwright/browser fallbacks sequential or very tightly bounded.
- Apply deterministic title, location, age, salary, visa, and exclusion filters before expensive matching.
- Canonicalize URLs and company names.
- Keep scan history and provider health.
- Use description fingerprints as an additional duplicate signal.
- Protect jobs with application history from destructive fuzzy merges.

Do not copy its Markdown/TSV inventory storage or lightweight title/company/URL ranking prompt. Resume Builder has stronger target preservation and criterion-level matching contracts.

### From CareerPulse

Reuse or preserve these capabilities:

- asynchronous HTTP base behavior;
- per-domain token-bucket rate limiting;
- retry/backoff, circuit breakers, and per-source timeouts;
- description enrichment for incomplete listings;
- location classification and remote-work confirmation;
- source progress and health reporting;
- full-description candidate matching as an optional second-stage signal.

Do not retain URL-heavy deduplication as the primary canonical identity, and do not represent malformed or failed AI scoring as a genuine zero score.

### From JobSpy

Use [speedyapply/JobSpy](https://github.com/speedyapply/JobSpy) as the preferred replaceable adapter for LinkedIn and Indeed. As of the 2026-08-27 review, it is the cleanest maintained GitHub integration found for both sources: one `scrape_jobs()` interface, concurrent source execution, proxy support, and a normalized job schema containing descriptions, compensation, dates, locations, remote state, and direct URLs when available.

This specifically replaces CareerPulse's Indeed HTML/Playwright scraper. JobSpy's Indeed adapter calls Indeed's GraphQL job-search endpoint and returns full posting descriptions, avoiding CareerPulse's repeatedly blocked HTML-card path. Its LinkedIn adapter still uses LinkedIn's public guest endpoints, so it should replace duplicated parsing code but not be mistaken for a block-proof source.

Recommended commercial-board acquisition shape:

```text
JobSpy adapter
    |- Indeed: primary commercial-board collector
    |- LinkedIn: conservative collector with description fetch enabled
    `- optional proxy pool after measured 429/partial-result failures
            |
            v
normalized job observation contract
            |
            v
inventory upsert and cross-source deduplication
```

Operational rules:

- Pin the `python-jobspy` version and keep the adapter boundary narrow because undocumented board endpoints can change.
- Run modest, staggered searches instead of attempting maximum pagination. JobSpy documents that LinkedIn commonly rate-limits around the tenth page from one IP.
- Set `linkedin_fetch_description=True` for records that may reach Resume Builder; the extra per-job requests are necessary for evidence-quality matching.
- For Indeed, do not combine `hours_old` with `is_remote` and assume both are honored. JobSpy currently treats those server-side filters as mutually exclusive; retrieve by freshness and enforce remote/location eligibility locally.
- Treat zero results, HTTP blocking, and malformed payloads as source-health events, never as evidence that jobs closed.
- Resolve aggregator results to the employer ATS URL when possible and prefer that observation as canonical.
- Add paid proxies only after health data demonstrates they are necessary. Proxy credentials remain outside the repository.

Treat JobSpy results as discovery observations rather than authoritative canonical jobs:

- prefer a direct employer ATS observation when one is available;
- retain the JobSpy source URL as provenance;
- normalize compensation intervals, location, job type, remote state, and dates;
- expect blocking and partial-result behavior;
- never let a failed commercial-board scrape close an employer-ATS job.

### From freehire

Adopt these data-model ideas:

- stable provider/external identities;
- content hashes to distinguish unchanged, updated, and reopened jobs;
- explicit open/closed lifecycle rather than age-only deletion;
- authoritative-source sweeps that close jobs only after successful complete scans;
- configuration-driven board registries.

Do not adopt its distributed indexing infrastructure unless the personal inventory grows beyond what SQLite FTS5 can comfortably search.

### From Job Seek

Adopt these operational ideas if the inventory becomes long-running:

- claimable work with bounded retries;
- separate cheap HTTP work from browser work;
- explicit taxonomy fields for role, seniority, technology, location, language, and compensation;
- canonical postings from monitored employer boards.

Redis, Typesense, and a distributed crawler are unnecessary for the initial personal system.

### From job_search

Adopt:

- save results as each source completes so a partial run retains useful work;
- saved inventory queries and filter presets;
- full-text search over normalized job fields;
- versioned match analyses rather than overwriting the only score.

## Inventory data model

The inventory should distinguish a provider observation from a canonical job.

### `job_observations`

One row per provider's representation of a posting:

| Field | Purpose |
|---|---|
| `id` | Internal observation ID |
| `provider` | `greenhouse`, `lever`, `jobspy-linkedin`, and so on |
| `provider_board_id` | Company/tenant board identity |
| `provider_job_id` | Stable provider job/requisition ID when available |
| `source_url` | URL returned by the provider |
| `canonical_url` | Tracking-cleaned apply or employer URL |
| `company_raw` | Source-provided company |
| `title_raw` | Source-provided title |
| `location_raw` | Source-provided location |
| `description_raw` | Preserved untrusted posting body |
| `posted_at` | Provider publication timestamp, when trustworthy |
| `first_seen_at` | First inventory observation |
| `last_seen_at` | Most recent successful observation |
| `content_hash` | Hash of normalized posting content |
| `fetch_status` | Complete, partial, blocked, malformed, or failed |
| `raw_payload_ref` | Optional diagnostic reference, not candidate evidence |

Unique identity should prefer `(provider, provider_board_id, provider_job_id)`. When a provider exposes no stable ID, fall back to `(provider, canonical_url)`.

### `jobs`

One row per canonical opportunity:

| Field | Purpose |
|---|---|
| `id` | Stable internal job ID |
| `preferred_observation_id` | Best representative source, normally direct ATS |
| `normalized_company` | Alias-aware canonical employer |
| `normalized_title` | Clean display title |
| `role_family` | Controlled role taxonomy |
| `seniority` | Normalized level |
| `work_mode` | Remote, hybrid, onsite, or unknown |
| `locations` | Normalized location set |
| `employment_type` | Full-time, contract, and so on |
| `salary_min/max/currency/interval` | Structured compensation |
| `posted_at` | Best trustworthy source date |
| `first_seen_at` | Inventory discovery date |
| `last_seen_at` | Liveness date, never treated as posting freshness |
| `closed_at` | Explicit lifecycle state |
| `canonical_fingerprint` | Conservative multi-signal identity |
| `source_quality` | Direct ATS, employer page, aggregator, or repost |
| `description_quality` | Complete, partial, enriched, or missing |

### `job_observation_links`

Link all provider observations to the canonical job rather than dismissing extra copies. Preserve the reason and confidence for every merge.

## Canonicalization and deduplication

Use a hierarchy rather than one fuzzy hash.

### Tier 1 — exact source identity

Match the same provider, board, and external job ID. This is safe for automatic linking.

### Tier 2 — canonical employer URL

Normalize host casing, path casing where appropriate, trailing slashes, known tracking parameters, and redirect wrappers. Exact canonical URLs may link automatically.

### Tier 3 — requisition and employer identity

Match normalized employer plus requisition ID across sources. This may link automatically when both fields are trustworthy.

### Tier 4 — conservative canonical fingerprint

Compare normalized employer, title family, location, description fingerprint, and publication window. High-confidence matches can form a duplicate cluster, but the direct ATS observation should be preferred rather than deleting the alternatives.

### Tier 5 — similarity suggestion

Title or embedding similarity alone produces a review suggestion. It must not merge two distinct openings automatically, especially when either job has been shortlisted, targeted, applied to, or interviewed for.

## Source preference

When several observations represent one job, choose the display source in this order:

1. Direct employer ATS with stable external ID and complete description.
2. Direct employer career page or structured JSON-LD.
3. Government or authoritative public API.
4. Specialist board carrying the employer's direct apply URL.
5. General aggregator.
6. Commercial-board repost or search result.

An older direct ATS record may still be preferred over a newer repost if the ATS remains open. Freshness comes from the posting date and first-seen time, not from the latest aggregator crawl.

## Future Resume Builder integration

Version one stops after updating the canonical inventory. It performs no candidate-aware ranking, shortlisting, or resume matching.

A later Resume Builder job screen may query or export active inventory records, apply private candidate evidence locally, and preserve only selected targets. The posting remains untrusted target material: it may guide evidence selection but must never enter `vault/facts/` or establish candidate experience.

The future flow remains:

```text
inventory update
    -> Resume Builder job screen
    -> user shortlist decision
    -> preserved target snapshot
    -> detailed evidence match
    -> tailored resume
```

## Integration contract

The inventory should expose a stable, tool-independent handoff. A JSON envelope is preferable to direct database coupling.

```json
{
  "schema_version": 1,
  "inventory_job_id": "job_01...",
  "preferred_observation": {
    "provider": "greenhouse",
    "provider_job_id": "123456",
    "url": "https://job-boards.greenhouse.io/example/jobs/123456"
  },
  "company": "Example",
  "role": "Senior Support Operations Engineer",
  "description_markdown": "# Job posting...",
  "published_at": "2026-08-26T14:30:00Z",
  "captured_at": "2026-08-27T12:00:00Z",
  "content_sha256": "...",
  "role_family": "support-operations",
  "work_mode": "remote",
  "locations": ["United States"],
  "compensation": {
    "currency": "USD",
    "interval": "yearly",
    "minimum": 150000,
    "maximum": 190000
  },
  "observations": [
    {
      "provider": "greenhouse",
      "url": "https://job-boards.greenhouse.io/example/jobs/123456"
    },
    {
      "provider": "jobspy-linkedin",
      "url": "https://www.linkedin.com/jobs/view/987654321"
    }
  ]
}
```

Resume Builder should validate the envelope, verify the description hash, derive or review target criteria, and write a canonical target only after the shortlist/save boundary is crossed.

## Ownership boundary

| Concern | Owner |
|---|---|
| Scraper adapters and board credentials | Inventory system |
| Rate limits, retries, incremental checkpoints, and source health | Inventory system |
| Raw provider payloads and mutable observations | Inventory system |
| Job canonicalization, lifecycle, and duplicate clusters | Inventory system |
| Candidate-specific search and retrieval projection | Resume Builder, exported read-only in a later integration |
| Candidate-aware ranking and job screening | Resume Builder |
| Private candidate evidence | Resume Builder vault only |
| Criterion-level semantic screen | Resume Builder |
| Preserved target snapshot | Resume Builder `targets/` |
| Detailed evidence audit | Resume Builder matching |
| Tailored resume and review lifecycle | Resume Builder |

## Proposed implementation phases

### Phase 0 — validate the commercial-board dependency

1. Pin a JobSpy version in an isolated spike.
2. Run representative LinkedIn and Indeed searches using the initial role families and United States remote configuration.
3. Measure description completeness, direct-link coverage, duplication, blocking, and incremental-date behavior.
4. Save sanitized response fixtures and confirm the backend-owned observation contract can represent both sources without leaking JobSpy types.

### Phase 1 — build the standalone inventory CLI

1. Create the independent local project and packaged `job-puller` command without adding a Git remote or publishing configuration.
2. Add the versioned configuration schema, global provider switches, and helpful `config validate` command.
3. Use SQLite with WAL and FTS5 plus tested Alembic migrations.
4. Implement the provider registry and capability declarations.
5. Support LinkedIn and Indeed through JobSpy plus Greenhouse, Lever, Ashby, SmartRecruiters, and Workday adapters.
6. Implement bounded fetch concurrency, serial writes, per-domain limits, retry semantics, persisted source health, and per-provider checkpoints.
7. Store raw observations, canonical jobs, source links, lifecycle state, content hashes, and reversible duplicate links.
8. Make repeated and interrupted manual runs idempotent.

### Phase 2 — harden inventory quality

1. Add same-run description enrichment and retryable enrichment failures.
2. Resolve commercial-board observations to direct ATS postings when available.
3. Implement conservative duplicate merging and canonical source preference.
4. Implement explicit active, possibly-closed, closed, and reopened transitions without destructive deletion.
5. Enforce 30-day raw-payload retention while preserving normalized provenance.
6. Add provider contract tests, lifecycle fixtures, migration tests, source-health summaries, and backup/restore documentation.
7. Verify that a fresh install can configure and run every provider independently.

### Phase 3 — integrate Resume Builder later

1. Define and test the inventory-to-target JSON schema after real inventory records exist.
2. Add a stable inventory CLI export command without exposing internal tables.
3. Add a read-only Resume Builder command that validates and previews one handoff without writing a target.
4. Add a separate explicit command that preserves an approved handoff as a target snapshot.
5. Route preserved targets through Resume Builder's existing screen and detailed-match contracts.
6. Keep all candidate-aware ranking, feedback, and tailoring outside the inventory backend.

## Success measures

Scraper success should not be measured only by job count.

Track:

- direct-ATS share of canonical jobs;
- duplicate compression ratio;
- percentage with complete descriptions and canonical apply URLs;
- trustworthy posted-date coverage;
- source failure and zero-result streaks;
- median time from employer posting to inventory discovery;
- enrichment success and retry rates;
- checkpoint lag and overlap deduplication rate;
- idempotency across repeated runs;
- number of unresolved possible-duplicate clusters.

For version one, the primary product metric is **fresh, complete, canonical jobs added per successful manual run**, not total raw rows scraped. Pursuable jobs per review session becomes the downstream metric only after Resume Builder integration exists.

## Final recommendation

Build **Job Puller**, a new standalone local Python inventory backend at `/Users/jordan/Projects/job-puller`. Keep it private and local-only. Use **career-ops only as the provider and ingestion blueprint**, **JobSpy as the LinkedIn/Indeed commercial-board adapter**, **freehire and Job Seek as canonical lifecycle/search references**, and **CareerPulse only as a read-only reference for resilient fetch/enrichment patterns**.

Do not extend CareerPulse, link to its database, or make the new backend depend on either CareerPulse or career-ops at runtime. Port or adapt only the narrowly selected behavior into backend-owned interfaces and tests.

Keep **Resume Builder as the sole owner of candidate-aware screening, target preservation, evidence matching, and resume tailoring**.

The result is not one giant merged application. It is a clean pipeline with a narrow handoff:

```text
best available inventory
    -> privacy-safe retrieval
    -> Resume Builder screen
    -> user shortlist decision
    -> preserved target
    -> detailed evidence match
    -> tailored resume
```
