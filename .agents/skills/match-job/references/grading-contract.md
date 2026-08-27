# Shared job-match grading contract

Use one semantic criterion matrix for both the quick screen and the detailed
job match. The classifier turns evidence judgments into a fixed match label; it
does not decide the judgments, measure resume quality, or predict an employer's
decision.

## Classification case

Create a version 1 JSON object with every material resume-evaluable criterion:

```json
{
  "version": 1,
  "evidence_complete": true,
  "criteria": [
    {
      "criterion_id": "incident-response",
      "importance": "required",
      "requirement_type": "mandatory-role-defining",
      "status": "met",
      "evidence_sufficiency": "high",
      "confidence": "high",
      "evidence_blocks": ["experience[0].bullets[0]"],
      "evidence_fact_ids": ["OPS-001"],
      "substitution_basis": "",
      "gap": ""
    }
  ]
}
```

Allowed requirement types are:

- `mandatory-role-defining`: a stated minimum central to the daily work;
- `mandatory-substitutable`: a stated minimum for which the posting explicitly
  accepts an equivalent; record that exact permission under
  `substitution_basis` so adjacent tools cannot silently count as equivalent;
- `supporting`: required or important work that is not an independent
  eligibility gate;
- `preferred`: an advantage rather than a minimum; and
- `lifestyle`: location, schedule, travel, employment, or compensation fit,
  reported separately from capability match.

Allowed statuses are `met`, `partial`, `not_met`, and `undecidable`. A `met` or
`partial` judgment requires both visible resume blocks and canonical fact IDs.
Every non-`met` judgment requires a concrete gap. Use `evidence_complete: false`
only when the posting or known candidate sources are genuinely unfinished; do
not use it to soften a completed search that found no support.
Record `confidence` separately from `evidence_sufficiency`: sufficiency judges
the strength of the cited proof, while confidence judges the reviewer's
certainty that the criterion was interpreted and classified correctly.

## Gate order

The deterministic classifier applies these rules:

1. Incomplete required evidence with an `undecidable` criterion produces
   `Unknown match`.
2. A completed search with an unsupported `mandatory-role-defining` or
   `mandatory-substitutable` requirement produces `Weak match`.
3. Any remaining required `partial`, `not_met`, or `undecidable` criterion
   produces `Partial match`.
4. When every resume-evaluable required criterion is `met`, the result is
   `Strong match`.

Preferred and lifestyle gaps remain visible but do not lower the capability
label. Resume polish, factual integrity, exact phrase retrieval, and career
potential may not upgrade the label.

Run the classifier without writing workspace artifacts:

```bash
resume-builder match classify /tmp/job-screen-classification.json
```

For a captured target and detailed match, attach the same case:

```bash
resume-builder match targets/<posting>.md resumes/<resume>.md \
  --classification-case /tmp/job-screen-classification.json
```

The attached case must cover every resume-evaluable target criterion exactly
once, preserve its required/preferred importance, and cite only fact IDs used by
the matched resume. The detailed matcher may refine evidence and status after a
deeper search, but it must explain any changed criterion judgment; it may not
silently replace the screen's label with a more favorable one.

## Outcome boundary

Record rejections, interviews, and offers as outcome evidence when the user asks
to preserve them. An outcome may calibrate future process review, but it never
proves which criterion controlled an employer's decision and never rewrites the
candidate's career facts.
