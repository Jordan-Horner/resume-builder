# Architecture

```text
CLI
  -> configuration validation
  -> provider registry
       -> JobSpy: LinkedIn / Indeed
       -> HTTP: Greenhouse / Lever / Ashby / SmartRecruiters / Workday
  -> description enrichment
  -> observation normalization
  -> conservative canonicalization
  -> SQLite inventory + FTS5
```

Provider modules own transport and source-shape translation only. The service owns checkpoints and orchestration. The database owns transactions, migrations, observation identity, canonical links, lifecycle state, source preference, and full-text indexing. No downstream consumer may depend on JobSpy or provider payload shapes.

Version one deliberately excludes scheduling, a web server, candidate ranking, resume access, application automation, and destructive fuzzy deduplication.

