# Role research contract

Use this contract to convert current role evidence into a direction profile.
The output describes the target market; it does not describe the candidate.

## Research frame

Record these choices before searching:

- role family and excluded title collisions;
- seniority and individual-contributor versus people-manager scope;
- geography or labor market when it materially changes expectations;
- anchor posting, if supplied;
- adjacent titles that belong in the peer set.

Use an **anchor plus portable core** model. The anchor establishes the specific
opportunity and useful differentiators. Peer roles establish what transfers
across employers. Official frameworks provide stable role mechanics that a
single posting may omit.

## Source quality and stopping rule

Prefer sources in this order:

1. Current official employer career pages or official ATS postings.
2. Official professional, government, or operational frameworks.
3. Reputable industry research with a disclosed method.
4. Aggregators only for discovery or a clearly disclosed fallback.

Do not use generic resume blogs, generated job-description pages, or search
snippets as authoritative market evidence. Verify that a posting is readable
and current enough for the requested market. Record its URL, descriptive
reference, and `as_of` date in the profile.

Aim for enough peer postings to cover different employers and adjacent titles,
often 10–20 when available. This is a diversity target, not a fixed quota.
Stop when new credible sources repeat the established shape, or when the
available market is exhausted. State the actual sample size, source mix,
geography, and gaps in the human-readable profile notes. Do not manufacture
percentages from a small or convenience sample.

## Extraction matrix

For every source, capture only what is explicit:

- title, seniority, reporting scope, and whether direct reports are stated;
- before-, during-, and after-event responsibilities where relevant;
- operational or program ownership;
- technical depth and hands-on expectations;
- cross-functional coordination and influence without authority;
- communication audiences, customer judgment, and executive exposure;
- coaching, facilitation, training, or team enablement;
- outcomes, metrics, scale, on-call, and service expectations;
- tools, certifications, education, and years of experience;
- sector-, company-, or regulatory-specific requirements.

Analyze six balanced dimensions even when one has no evidence:

1. Operational and process ownership
2. Technical judgment and execution
3. Customer and stakeholder communication
4. Cross-functional influence and coordination
5. People leadership and team enablement
6. Metrics, outcomes, and continuous improvement

Absence is meaningful. Do not translate frequent technical nouns into a
technical-first role when the responsibilities center on people, decisions, or
operational control.

## Classification

Classify each proposed concept before writing it:

- **portable core**: repeated across credible peer sources;
- **anchor differentiator**: important to the target posting but not broadly
  established;
- **seniority-specific**: expected only at a particular scope;
- **sector/company-specific**: retain only as a labeled overlay;
- **needs review**: plausible but not adequately sourced;
- **candidate evidence gap**: the role calls for it, but the vault does not yet
  prove it.

Weights express narrative priority, not keyword frequency. A concept should
earn a high weight when it is central to role outcomes and corroborated across
strong sources. Avoid counting synonyms as separate priorities.

## Database record

Write one canonical Markdown profile at `directions/<slug>.md` using the
direction schema. Include:

- primary and peer titles without collapsing materially different role
  families;
- audiences and one positioning statement;
- distinct weighted concepts with terms, candidate evidence themes, basis, and
  source IDs;
- de-emphasis and avoid-term boundaries;
- measurable resume success criteria;
- stable `DIRSRC-NNN` entries for every user, research, or outcome source;
- human-readable sections for portable core, anchor overlay, research coverage
  and limitations, and the candidate-evidence boundary.

For an existing profile, preserve IDs and intent that remain valid. Add sources
and refine concepts in place. Report concepts added, removed, reweighted,
reclassified, or left unresolved. Git history is the version record.

## Evidence boundary

Direction `evidence_themes` are queries against the candidate vault, not proof.
If the vault lacks a required theme, report a candidate evidence gap. Research
may guide a pointed career-history question, but any answer must go through
`hydrate-vault` before it supports a final resume. Never convert role-market
research into a candidate claim.
