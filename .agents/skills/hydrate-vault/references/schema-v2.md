# Vault schema v2

Schema v2 keeps the atomic, source-grounded v1 layout and adds first-class role
scope for employment facts.

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

`vault.json` declares `"schema_version": 2` and the relative canonical paths.
Every fact has one file. Employment indexes contain metadata and fact IDs, not
duplicated narratives.

## Atomic facts

All facts require `schema_version`, immutable `id`, `title`, `type`, `status`,
`category`, one or more registered `sources`, and one or more `themes`.
Employment facts also require an `organization` matching their index.

Allowed types are `role`, `responsibility`, `accomplishment`, `project`,
`incident`, `leadership`, `feedback`, and `story`. Status is `confirmed`,
`approximate`, or `needs-review`. Categories are `profile`, `skills`,
`education`, `certifications`, `projects`, and `employment`.

`confirmed` applies to the complete fact, not to isolated words within it. A
composite fact may join clauses only when its cited evidence explicitly supports
the combined actor, action, mechanism, chronology, and outcome. Do not attach an
outcome from an older resume to a mechanism described by a later source merely
because they sound compatible. Split independently supported claims or mark the
unresolved relationship `needs-review`. Prior and generated resumes remain
claims to evaluate; their polished wording is not extra evidence.

### Role facts

A role fact identifies one title and supported date period. It does not carry
`scope` or `role_ids`:

```markdown
---
schema_version: 2
id: EX-002
title: Production Services Tech Lead
type: role
status: confirmed
category: employment
organization: example-co
sources:
  - SRC-0123456789ab
themes:
  - leadership
---
```

### Other employment facts

Every non-role employment fact declares one of two scopes:

- `scope: role` requires one or more `role_ids` from the same organization.
- `scope: organization` is used only when the evidence does not establish a
  reliable role period, and must not include `role_ids`.

```markdown
---
schema_version: 2
id: EX-003
title: High-severity production investigation ownership
type: leadership
status: confirmed
category: employment
organization: example-co
scope: role
role_ids:
  - EX-002
sources:
  - SRC-0123456789ab
themes:
  - incident-response
---
```

Role assignment is a source claim, not a generation preference. Hydration must
ask when an employer has multiple roles and period placement materially matters.
If the available sources remain ambiguous, preserve the fact at organization
scope. The synthesis validator prevents a role-scoped fact from appearing under
an incompatible resume entry.

## Employment indexes and sources

Employment indexes use `schema_version: 2`; every indexed fact must exist and
carry the same organization, and every employment fact appears in exactly one
index. Source IDs retain the form `SRC-<12 hex chars>` derived from the original
file digest. Never hand-edit or reuse IDs.

## Migration and validation

Use `resume-builder upgrade --vault-root vault` to preview v1-to-v2 changes and
add `--apply` only after reviewing ambiguous multi-role assignments. The upgrade
stages and strictly validates the complete v2 vault before applying, and keeps a
local recovery copy. Run `resume-builder validate --vault-root vault --strict`
after any canonical change.

Canonical writes still use the [change-plan v1 contract](plan-v1.md). Resume
generation cites fact IDs but never edits facts or role scope.
