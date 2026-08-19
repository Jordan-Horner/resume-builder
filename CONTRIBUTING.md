# Contributing

Resume Builder separates its reusable engine from every user's private career
workspace. Contributions should target the engine, tests, schemas, templates,
agent workflows, fictional fixtures, or documentation. They must never introduce
real career material.

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
ruff check src tests scripts .agents/skills/hydrate-vault/scripts
ruff format --check src tests scripts .agents/skills/hydrate-vault/scripts
mypy src
python -m build
python scripts/audit_distribution.py
```

Use focused commits. Update tests for behavior changes and documentation for
new commands, schemas, workflow states, or release gates.

The complete test suite installs Chromium through Playwright. A pull request
should pass the same test, lint, format, type, build, distribution, and fictional
fixture checks defined in `.github/workflows/ci.yml`.

## Data and privacy rules

- Use fictional fixtures in tests and examples.
- Never commit real resumes, source documents, contact details, credentials,
  identity documents, private job-search information, or confidential employer
  artifacts.
- Never use role research or job-posting text as candidate evidence.
- Preserve atomic fact IDs and provenance through validated change plans.
- Report security and privacy concerns privately as described in `SECURITY.md`.

Do not place sensitive material in a public issue or pull request, even when the
material is later deleted. Git history preserves earlier versions.

Unless explicitly stated otherwise, contributions accepted into this project are
licensed under the Apache License 2.0.
