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
