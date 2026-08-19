# Career Vault

This directory contains schema-versioned career information hydrated from
reviewed sources.

- `vault.json` declares the schema version and canonical paths.
- `facts/` holds one Markdown file per canonical fact, organized by category.
- `facts/employment/<slug>/` holds employer-linked facts.
- `employment/` holds organization metadata and indexes its fact IDs.
- `sources/` preserves normalized source snapshots and their manifest.
- `hydration-report.md` records what was imported and what still needs review.

Every fact must carry schema version 2 frontmatter, a stable ID, a type, a review
status, themes, and at least one source ID. Databases, role summaries, and search
indexes may be generated from these files later, but they never replace them.
