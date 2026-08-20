# Design decisions

## Why Markdown and Git instead of a mutable profile database?

Career information changes slowly, benefits from human-readable diffs, and
must preserve provenance. Markdown keeps the durable record inspectable while
Git supplies history, branching, and recovery without making a generated index
the source of truth.

## Why one fact per file?

Atomic facts make provenance, status, employment scope, and conflicts visible
at the smallest reusable unit. They also prevent a mechanism from one source
being silently combined with an outcome from another.

The tradeoff is file count. That is acceptable because humans review changes
through plans and Git diffs while software handles indexing and validation.

## Why separate directions from candidate facts?

A role profile describes what an employer may value. It does not prove the
candidate has done it. Keeping the two stores separate prevents role research
and job-posting language from leaking into the resume as invented experience.

## Why plan before drafting?

Directly prompting from a fact list encourages one-fact-per-bullet output,
keyword stuffing, and accidental loss of career progression. A versioned
synthesis plan makes selection, omission, story purpose, role arcs, evidence
composition, and page budget reviewable before polished language obscures the
decisions.

## Why deterministic checks and human review?

Deterministic checks are good at structure, hashes, identifiers, status,
numeric support, and narrow authorship rules. They cannot decide whether a
sentence sounds natural or whether the resume makes a convincing hiring case.

The independent cold review is therefore a separate gate. It sees the visible
resume first, before evidence rationale can bias the language judgment.

## Why hash-pin review records?

An approval is meaningful only for the exact prose and evidence that were
reviewed. Hashes make stale approval detectable when a resume, plan, direction,
target, cited fact, or generated package changes.

## Why preview before PDF?

HTML is the continuous review surface; PDF pagination is a release concern.
Separating them makes user approval explicit and prevents repeated browser
rendering during ordinary content iteration.

## Why no universal ATS score?

Exact term retrieval and semantic qualification are different questions.
Resume Builder reports discoverability evidence and a cited criterion review,
but does not fabricate a pass probability or employer decision.

## Why an ignored nested repository instead of a required Git submodule?

Each user's private workspace may have a different private remote—or no remote
at all. A committed submodule would put a user-specific URL and Git link into
the reusable engine checkout. Resume Builder therefore keeps `workspace/`
ignored by the engine and initializes it as an independent nested repository.
This preserves one visible project folder and separate history without making
private workspace configuration part of the engine repository. Advanced users
may manage that private repository with their preferred Git workflow.

## Why `resume-vault` is the default private repository name

The private workspace has one stable purpose regardless of who installs the
engine: it is the user's career vault and resume history. Onboarding therefore
defaults to `<authenticated-owner>/resume-vault`. Users can override the full
`OWNER/NAME`, but the engine does not generate project-specific or numbered
vault names that make backups harder to recognize later.

## Known tradeoffs

- The workflow has more ceremony than a one-shot generator.
- Canonical hydration requires judgment before facts become reusable.
- Strong staleness rules intentionally cause rebuild and re-review work.
- The current CLI favors explicit artifacts over a graphical interface.
- Versioned synthesis and review schemas remain deliberately detailed. Their
  workflow facades are small, while architecture checks prevent reverse imports
  and orchestration cycles from returning as those contracts grow.
