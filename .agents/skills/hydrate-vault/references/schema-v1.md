# Vault schema v1

## Contents

- Canonical layout
- Vault declaration
- Atomic facts
- Employment indexes
- Source IDs
- Hydration report
- Resume references

## Canonical layout

```text
vault/
  vault.json
  facts/
    profile/<fact-id>.md
    skills/<fact-id>.md
    education/<fact-id>.md
    certifications/<fact-id>.md
    projects/<fact-id>.md
    employment/<organization-slug>/<fact-id>.md
  employment/<organization-slug>.md
  sources/manifest.json
  sources/normalized/<source-id>.md
  hydration-report.md
```

Every fact has one canonical file. Employment index files contain metadata and
fact IDs, never duplicated fact narratives.

## Vault declaration

`vault/vault.json` selects the schema and canonical paths:

```json
{
  "schema_version": 1,
  "facts_path": "facts",
  "employment_path": "employment",
  "sources_manifest": "sources/manifest.json"
}
```

Reject unknown schema versions. Future schema changes require an explicit,
validated migration. `prepare_sources.py` creates this declaration and the
canonical directories when hydrating a new empty vault.

All declared paths must be relative, traversal-free, contained by the vault,
and distinct. The normalized source directory is `normalized/` beside the
configured source manifest.

## Atomic facts

Name each fact file `<FACT-ID>.md`. Use YAML frontmatter and a Markdown body:

```markdown
---
schema_version: 1
id: EX-005
title: "Integrated investigation workflow"
type: accomplishment
status: approximate
category: employment
organization: example-corp
sources:
  - SRC-0123456789ab
themes:
  - investigation-speed
  - workflow-automation
---

# Integrated investigation workflow

Grounded factual narrative with qualified language preserved.
```

Required fields:

- `schema_version`: `1`
- `id`: immutable uppercase prefix plus three digits
- `title`: short factual label
- `type`: one allowed fact type
- `status`: one allowed review status
- `category`: canonical directory category
- `sources`: one or more registered source IDs
- `themes`: one or more reusable tags

Employment facts also require `organization`, matching an employment slug.

Allowed `type` values:

- `role`
- `responsibility`
- `accomplishment`
- `project`
- `incident`
- `leadership`
- `feedback`
- `story`

Allowed `status` values:

- `confirmed`
- `approximate`
- `needs-review`

Allowed `category` values:

- `profile`
- `skills`
- `education`
- `certifications`
- `projects`
- `employment`

Never reuse or renumber a fact ID. Reclassification may move the file, but its ID
and Git history remain stable.

## Employment indexes

Use `vault/employment/<slug>.md`:

```markdown
---
schema_version: 1
organization: "Example Corp"
slug: example-corp
status: confirmed
sources:
  - SRC-0123456789ab
fact_ids:
  - EX-001
  - EX-002
---

# Example Corp
```

Every indexed ID must exist and carry the same organization slug. Every
employment fact must appear in exactly one employment index.

## Source IDs

`prepare_sources.py` assigns immutable IDs in the form `SRC-<12 hex chars>` from
the SHA-256 digest of the original file. Exact duplicate files share a source ID.
Never hand-edit a source ID.

## Hydration report

Record source counts, canonical fact counts, status/type/category counts,
duplicates, conflicts, exclusions, empty extractions, and unresolved review
items. Treat the report as an audit summary, not a factual source.

## Resume references

Future resume bullets may cite facts with invisible comments:

```markdown
- Resume bullet text. <!-- evidence: EX-001 EX-004 -->
```

Hydration never creates these bullets or writes under `resumes/`.

## Canonical change plans

Agents propose fact, employment-index, and hydration-report writes using the
[change-plan v1 contract](plan-v1.md). The deterministic plan command validates
the complete staged vault before applying optimistic, non-deleting writes.
