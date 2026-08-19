# Public release checklist

This engine directory is the history-free public candidate. The parent
repository is the private working vault and must never be made public or used
as the source history for the eventual portfolio repository.

## Prepare here

- [x] Architecture and design-decision documentation
- [x] Portfolio case-study draft
- [x] Demo recording script
- [x] Contribution and security guidance
- [x] Changelog structure
- [x] Fictional end-to-end fixture
- [x] Sanitized architecture, project-health, and review-gate visuals
- [x] Full Chromium PDF minting test with rendered and extracted-text QA
- [x] Fresh wheel installation and blank first-run workspace simulation
- [x] Zero private-text overlap, known-identifier findings, or detected secrets
- [x] Source archive contains the complete Phoenix demonstration; wheel contains
      only the engine and blank workspace scaffolding
- [ ] Optional fictional sample PDF for the portfolio walkthrough
- [ ] Final license choice
- [ ] Tagged private milestone

## Create later in a new history-free repository

- Export from an explicit allowlist; do not clone and delete private files.
- Include the engine, tests, reusable skills, templates, documentation, and
  fictional demo only.
- Replace every candidate, employer, source, target, contact detail, and output
  with fictional material.
- Scan both tracked files and generated artifacts for private identifiers.
- Initialize new Git history after the allowlisted export is complete.
- Run the complete test and demo workflow in a clean environment.
- Select and add the software license in the clean repository. Apache-2.0 is a
  strong default when an explicit patent grant is desired; MIT is simpler.
- Publish only after reviewing the resulting repository in a browser while
  signed out.

## Repeatable release checks

Build from a clean checkout, then run:

```bash
python -m build
python scripts/audit_distribution.py
```

For the final private-to-public export, create an untracked text file containing
private names, email addresses, employer names, source paths, and any other
known identifiers, one per line, then run:

```bash
python scripts/audit_distribution.py --denylist-file /exact/private/denylist.txt
```

The audit rejects runtime workspace paths from both archives, restricts the
wheel to the CLI package and package metadata, requires blank workspace
scaffolding, requires the approved fictional demo in the source archive, and
scans text members against the optional private denylist. CI separately scans
Git history for credential-shaped secrets. The denylist is deliberately not
committed because its contents are private.

## Never export

- `vault/`
- Current `resumes/`, `targets/`, or `build/`
- Git history from this repository
- Registered source paths or normalized snapshots
- Review records containing private resume text
- Intake notes or job-search material
