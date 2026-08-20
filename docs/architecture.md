# Architecture

![Resume Builder architecture](assets/architecture.png)

Resume Builder separates durable evidence from generated presentation. The
boundary is deliberate: changing a sentence should not change the underlying
career history, and passing a structural check should not be mistaken for
editorial approval.

## Layers

1. **Sources** preserve imported resumes and notes as untrusted evidence.
2. **Canonical facts** store one versioned claim per Markdown file with source
   provenance, employment scope, and confirmation status.
3. **Directions and targets** describe the role being pursued. They guide
   selection but can never become candidate evidence.
4. **Synthesis plans** make story selection, omissions, reviewer risks, and
   evidence composition inspectable before prose is written.
5. **Resume Markdown** is the only editable presentation source. Every factual
   block cites canonical fact IDs.
6. **Verification** checks structure, evidence status, numeric claims,
   authorship language, direction coverage, job-specific retrieval, and stale
   inputs.
7. **Selection review** freezes the non-prose hiring argument, including chosen
   and omitted stories, and must approve it before wording review begins.
8. **Editorial review** freezes a cold-read package, records a decision for
   every narrative block, and pins the decision to exact input hashes.
9. **Preview and minting** publish only a reviewed build. PDF minting adds page
   budget, overflow, network, JavaScript, and text-extraction checks.

## Trust boundaries

| Input | What it may influence | What it may not establish |
|---|---|---|
| Imported resume or career note | Candidate fact proposals | Canonical truth without review |
| Role research | Direction and terminology | Candidate experience |
| Job posting | Selection and match criteria | Candidate experience |
| Language model | Drafting and judgment | Unsupported facts or authority |
| Deterministic compiler | Traceability and structural integrity | Persuasiveness or semantic truth |
| Selection reviewer | Story choice and complete hiring argument | New facts or resume prose |
| Career-professional review | Language quality and hiring read | New factual evidence or story deletion |

## Dependency shape

The package is organized around functional workflows rather than a web-service
layering model. `atomic`, `layout`, `rendering`, and `validation` provide shared
boundaries. Higher-level modules orchestrate source import, synthesis,
compilation, verification, feedback, review, matching, preview, and minting.

Two imports are intentionally lazy: feedback acceptance needs compiled preview
and review freshness behavior, while compilation needs the effective guidance
snapshot. Keeping those imports inside the narrow call sites prevents import
time cycles. A future extraction should move shared guidance and review pins
into dependency-neutral modules before further expanding those workflows.

`review_records.py` is currently the largest module because it owns package
construction, decision finalization, wording-only repair, record loading,
freshness, and approval enforcement. The safest decomposition boundary is:

- `review_packages.py` for cold-read and evidence-appendix construction;
- `review_decisions.py` for finalization and repair application;
- `review_schema.py` for loading and validation;
- `review_freshness.py` for approval and staleness checks.

That split should happen as a behavior-preserving refactor with the current
test suite acting as the compatibility contract.

## Release invariants

- Canonical facts are never edited outside a validated change plan.
- A `needs-review` fact cannot appear in visible resume prose.
- High-authority verbs must be supported by the action evidence.
- A changed narrative block invalidates its previous approval.
- A changed fact, plan, direction, target, or build invalidates dependent
  reviews.
- Preview and mint cannot bypass rejected or incomplete language review.
- Language review cannot start before a current selection approval.
- PDF minting cannot bypass page-budget or extraction failures.
