# Architecture

```text
CLI
  -> configuration validation
  -> semantic title families
  -> provider registry
       -> JobSpy: Boolean family queries for LinkedIn / guarded title queries for Indeed
       -> HTTP: Greenhouse / Lever / Ashby / SmartRecruiters / Workday
  -> description enrichment
  -> observation normalization
  -> conservative canonicalization
  -> SQLite inventory + FTS5
```

Provider modules own transport and source-shape translation only. The service owns checkpoints and orchestration. The database owns transactions, migrations, observation identity, canonical links, lifecycle state, source preference, and full-text indexing. No downstream consumer may depend on JobSpy or provider payload shapes.

Commercial providers also own local eligibility accounting because they know which source limitations forced each
filter to run locally. Aggregate and family-level metrics flow through `ProviderResult`, appear in the CLI run
summary, and are stored as JSON on the scrape run.

Version one deliberately excludes scheduling, a web server, candidate ranking, resume access, application automation, and destructive fuzzy deduplication.
