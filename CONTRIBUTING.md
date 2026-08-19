# Contributing

Resume Builder currently develops inside a private career vault. Contributions
should target the reusable engine, tests, schemas, templates, or documentation
and must never introduce personal career material.

## Development setup

```bash
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m playwright install chromium
```

## Quality checks

```bash
pytest
ruff check src tests .agents/skills/hydrate-vault/scripts
ruff format --check src tests .agents/skills/hydrate-vault/scripts
mypy src
python -m build
resume-builder validate --strict
resume-builder direction validate
resume-builder match validate
resume-builder eval validate
```

Use focused commits. Update tests for behavior changes and documentation for
new commands, schemas, workflow states, or release gates.

## Data and privacy rules

- Use fictional fixtures in tests and examples.
- Never commit resumes, source documents, contact details, credentials,
  identity documents, or confidential employer artifacts.
- Never use role research or job-posting text as candidate evidence.
- Preserve atomic fact IDs and provenance through validated change plans.
- Report security and privacy concerns privately as described in `SECURITY.md`.
