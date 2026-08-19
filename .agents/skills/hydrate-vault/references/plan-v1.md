# Vault change plan v1

Use a change plan to separate semantic fact extraction from deterministic vault
writes. Store working plans under `build/`; they are review artifacts, never
factual sources.

```json
{
  "version": 1,
  "rationale": "Add source-grounded facts and synchronize employment indexes.",
  "writes": [
    {
      "path": "facts/employment/example/EX-003.md",
      "expected_sha256": null,
      "content": "---\nschema_version: 2\n..."
    },
    {
      "path": "employment/example.md",
      "expected_sha256": "64-lowercase-hex-characters",
      "content": "---\nschema_version: 2\n..."
    }
  ]
}
```

Rules:

- Use `null` only when adding a path that does not exist.
- Use the current full-file SHA-256 when updating an existing path.
- Target only configured fact files, employment indexes, or
  `hydration-report.md`.
- Include complete replacement content for every write.
- Never encode deletions. Hydration is additive and preservation-first.
- Preserve existing IDs, source references, manual wording, and unsupported
  facts unless the reviewed plan explicitly updates them.
- Run `plan validate` and `plan preview` before `plan apply`.

The apply command stages the complete vault, runs strict validation, rechecks
optimistic hashes, writes atomically, and rolls back if final validation fails.
