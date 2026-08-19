# Job Match Contract

## Boundary

Job matching has three inputs with different authority:

- `vault/facts/` supplies candidate facts.
- `directions/` supplies reusable role-family context.
- `targets/` supplies one real employer posting and its job-specific criteria.

The posting may change selection and emphasis. It may never create a candidate
fact. One posting also may not silently redefine the reusable role direction.

## Canonical target record

Store one record per posting under:

```text
targets/<company>-<role>-<posting-date>.md
```

Use a stable date or requisition identifier when no posting date exists. The
record has YAML frontmatter and a normalized Markdown snapshot:

```yaml
---
schema_version: 1
slug: company-role-2026-08-17
company: Company
role: Role
captured_at: 2026-08-17
source:
  kind: url
  reference: Official employer posting
  url: https://example.com/jobs/123
  published_at: 2026-08-10
  body_sha256: <sha256 of normalized body after frontmatter>
direction: directions/role-family.md
criteria:
  - id: singular-criterion
    importance: required
    label: Human-readable label
    description: One clear, objectively reviewable expectation.
    resume_evaluable: true
    source_section: Qualifications
search_groups:
  - id: relevant-retrieval-group
    criterion_id: singular-criterion
    any_of:
      - exact phrase
      - honest variant
---

# Job Posting Snapshot

Normalized source content follows.
```

Allowed source kinds are `url`, `pasted`, and `file`. `body_sha256` protects the
captured snapshot from unnoticed edits. Updating criteria or search groups is a
normal reviewed Git change; changing the body requires updating its hash and
explaining why the source snapshot changed.

Keep criteria focused. Four to eight usually describe a posting better than a
long task inventory, but use the number the source actually warrants, up to the
compiler limit. Each criterion must be singular enough that a reviewer can
distinguish full, partial, and missing evidence. Preserve the posting's own
required/preferred distinction. A criterion may use
`resume_evaluable: false` for work eligibility, an application question, or
another condition a resume cannot reliably prove.

Every resume-evaluable criterion needs at least one exact search group. An
`any_of` list represents honest language variants for one retrieval concept;
it does not mean the resume should contain all of them.

## Deterministic audit

`resume-builder match` verifies:

- target schema, filename, direction reference, and snapshot hash;
- resume structure and canonical fact grounding;
- exact configured phrases on token boundaries;
- the resume blocks and fact IDs associated with every match;
- whether a phrase is demonstrated in experience/projects or appears only in
  the headline, competencies, skills, or context;
- source, direction, resume, and baseline hashes; and
- evidence and retrieval deltas between baseline and tailored versions.

It does not verify semantic entailment, writing quality, employer preference,
or likely hiring outcome. Missing required retrieval is reported inside a valid
audit instead of being converted into a command failure or ATS pass/fail score.
Generated `.json` and `.md` reports under `build/matches/` are disposable.

## Semantic criterion review

Use exactly four statuses:

| Status | Meaning |
|---|---|
| `met` | Direct, credible resume evidence satisfies the criterion. |
| `partial` | Relevant evidence exists, but a material component is weak or absent. |
| `not_met` | Contrary evidence exists or the canonical vault confirms a real gap. |
| `undecidable` | The resume does not provide enough evidence to judge. |

For every judgment cite:

- the visible resume block;
- its canonical fact IDs;
- evidence sufficiency (`high`, `medium`, or `low`); and
- the concrete missing element, if any.

Do not turn `undecidable` into `not_met`. Do not turn a keyword match into
`met`. A skills-list match is useful for retrieval, but usually needs experience
or project proof before evidence sufficiency can be high.

## Baseline comparison

When a tailored resume exists, compare it with its closest approved directional
baseline. Report:

- exact retrieval groups gained and lost;
- required retrieval gaps closed or introduced;
- canonical fact IDs added and removed;
- meaningful evidence or progression weakened by tailoring;
- candidate argument and prioritization improved or blurred; and
- changes that merely copy posting language without adding proof.

The deterministic report supplies the first four raw deltas. The agent supplies
the semantic and career-professional judgment. Improved retrieval does not
automatically mean a better resume, and removed baseline content is not
automatically a regression when it is an intentional, defensible tradeoff.

## Result framing

Do not emit a universal percentage. A concise result should include:

- required and preferred criterion findings;
- strongest evidence and biggest resume-only objection;
- exact retrieval risk;
- baseline comparison when available;
- up to three high-value improvements; and
- one route per improvement: `rebuild`, `hydrate`, `direction`, or
  `accept-gap`.

Always label the result as a resume-only match. Other application materials,
screening questions, interviews, referrals, location policy, and employer
judgment remain outside its scope.
