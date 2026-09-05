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
python scripts/check_architecture.py
```

Use focused commits. Update tests for behavior changes and documentation for
new commands, schemas, workflow states, or release gates.

The complete test suite installs Chromium through Playwright. A pull request
should pass the same test, lint, format, type, build, distribution, and fictional
fixture checks defined in `.github/workflows/ci.yml`.

CI runs lint, formatting, and type checks once on Python 3.11 before starting
the Python matrix and pull-request container build. Both Python 3.11 and 3.14 run the full
test suite, including Chromium PDF tests. Architecture and committed demo-asset
audits already run inside pytest; their standalone commands remain useful locally.
Packaging, clean-install checks, and the fictional CLI demonstration run once on
Python 3.14. Frontend and secret checks run independently. New pull-request commits
cancel obsolete runs; main-branch publication remains serialized and non-cancelling.
After the main-branch checks pass, native AMD64 and ARM64 jobs build and test
registry candidates by digest. Publication combines those tested images and their
attestations without rebuilding; see [container releases](docs/container-deployment.md)
for promotion, partial-failure, and rerun behavior.

To exercise the same fresh-container startup check locally:

```bash
docker build --tag resume-builder-automation:ci .
sh scripts/smoke_container.sh resume-builder-automation:ci
```

The check uses no host mounts or credentials. It waits up to two minutes for
health, verifies the portal HTML and status response, checks that the scheduler
starts disabled, prints container logs on failure, and removes the container.
CI job timeouts bound dependency installation, builds, and checks as well.

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
