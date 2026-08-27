# Job Puller agent instructions

Job Puller is a private, local-only inventory collector. Preserve these boundaries:

- Do not add a Git remote, publishing workflow, telemetry, hosted service, GUI, scheduler, or authenticated job-board automation unless the user explicitly changes the product decision.
- Do not read resumes or candidate evidence. Candidate matching belongs to Resume Builder.
- Keep all provider-specific payloads behind the backend-owned `JobObservation` contract.
- A failed, blocked, partial, or suspiciously empty source run must not advance its checkpoint or close jobs.
- Never delete canonical jobs because a source stopped returning them. Preserve lifecycle and provenance.
- Never merge jobs using title similarity alone. Exact provider identity and canonical URLs are safe; uncertain matches are review suggestions.
- Keep personal configuration, database files, raw payloads, proxies, and tokens out of Git.
- Run `uv run ruff check .` and `uv run pytest` before finishing changes.

