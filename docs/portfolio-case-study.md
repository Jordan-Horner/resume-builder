# Portfolio case study

## Resume Builder

**A local-first, evidence-grounded system for building role-specific resumes
without losing or inventing career information.**

### The problem

Traditional resume editing repeatedly copies and rewrites documents. Strong
accomplishments disappear between versions, similar claims drift apart, and
AI-assisted rewrites can introduce authority, outcomes, or causal relationships
that the source material does not support.

### The approach

Resume Builder imports career material into a Git-tracked vault of atomic facts.
Role directions and job postings remain separate targeting inputs. A versioned
synthesis plan selects evidence and defines the job of each story before prose
is drafted. Deterministic verification checks traceability and stale inputs;
an independent cold review judges natural language and the hiring argument.
Only reviewed builds can become user-facing previews or audited PDFs.

### Engineering highlights

- Provenance-aware, additive, idempotent document ingestion
- Atomic career facts with confirmation and employment-scope states
- Evidence-linked Markdown compiler with authorship and numeric-claim gates
- Versioned role directions, job targets, and synthesis plans
- Baseline-versus-tailored regression and retrieval analysis
- Hash-pinned narrative-block review with stale-input detection
- Review-gated HTML preview and Playwright PDF minting
- Typed Python CLI, CI, full browser tests, and coverage enforcement

### Key design judgment

The central design decision was to keep deterministic integrity separate from
subjective quality. A passing compiler proves that a draft is structurally
traceable; it never claims the prose is persuasive or semantically perfect.
Likewise, a job posting can guide selection but can never become evidence that
the candidate has a skill.

### Current scale

- 27 Python modules
- 154 automated tests
- 77% statement coverage
- Python 3.10 and 3.14 CI matrix
- A history-free fictional legal-career fixture that exercises the same vault,
  synthesis, verification, and review boundaries as a private workspace

### What I would improve next

- Extract review packaging, schema validation, repairs, and freshness from the
  current review orchestration module.
- Record the final demo walkthrough using the approved Phoenix Wright fixture.
- Add a lightweight visual interface over the existing artifact workflow.
- Measure usability with users who maintain several resume directions.

### Interview discussion prompts

- Why atomic facts outperform a generated “master resume” for provenance
- Where deterministic AI guardrails help and where they create false confidence
- How hash-pinned reviews prevent stale approvals
- Why exact ATS retrieval and semantic job fit must be reported separately
- How the system prevents one source’s mechanism from inheriting another
  source’s outcome
