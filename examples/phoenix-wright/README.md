# Phoenix Wright fictional demo

This is an opt-in demonstration workspace. `resume-builder init` does not copy,
import, or merge any of these files into a user's private workspace. Run demo
commands from this directory only when you intentionally want to inspect the
fictional example.

This approved demonstration uses Phoenix Wright's fictional career to show how
Resume Builder handles a long legal history, linked proceedings, professional
discipline, reinstatement, collaborator credit, education, and incomplete
credential details without inventing facts.

Phoenix Wright and Ace Attorney are properties of Capcom. This repository does
not include game artwork, audio, scripts, or copied dialogue. The fixture uses
short factual career summaries with source links for demonstration and review.

## What the fixture demonstrates

- Source registration and canonical provenance
- Confirmed versus unresolved facts
- Supported role chronology and office-name changes
- A version 6 evidence-synthesis plan
- A legal resume with Education and attorney-status evidence
- An accepted, fixture-local editorial rule
- Automatic exclusion of three `needs-review` claims

The sources intentionally do not name a real-world bar jurisdiction or identify
the law degree as a J.D. or LL.B. The resume preserves those limits.

## Run it

From the engine repository after installation:

```bash
export RESUME_BUILDER_WORKSPACE="$PWD/examples/phoenix-wright/workspace"
resume-builder validate --strict
resume-builder direction validate
resume-builder synthesis resumes/plans/senior-defense-attorney.yaml
resume-builder verify resumes/baselines/senior-defense-attorney.md
```

`verify` creates disposable review inputs under the example workspace's
ignored `build/` directory. Use the included agent review workflow to complete
a fresh independent review before publishing a preview or minting a PDF.

The original research inputs are retained under `source-material/`; the
registered normalized snapshots live inside the example vault.

## Rebuild the canonical vault

The files under `source-material/` are immutable fixture inputs. Their exact
hashes and deterministic source IDs are pinned in
`bootstrap/source-lock.json`. Do not edit an existing input in place: add a
clearly named new source or addendum and update the lock and reviewed hydration
plan together. This restriction applies to the packaged demonstration, not to
user vaults, where revised resumes are registered additively as new evidence.

To prove that the approved canonical facts do not depend on a prebuilt vault,
start with a blank disposable workspace, register the two locked sources, and
apply `bootstrap/hydration-plan.json` through `resume-builder plan validate`,
`preview`, and `apply`. The test suite performs that complete reconstruction,
compares every canonical fact, employment index, and hydration-report entry
with the approved fixture, then reimports the sources and requires zero new
registrations.

The approved workspace also retains the historical `SRC-3aba7a92ce43`
normalized snapshot. Its original raw bytes were never committed, so it is
preserved for audit history but is not used as bootstrap evidence. Canonical
facts cite the current, approved, reproducible inventory source
`SRC-f953554da1da` instead.
