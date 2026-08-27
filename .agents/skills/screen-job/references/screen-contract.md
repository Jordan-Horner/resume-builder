# Job Screen Contract

## Purpose and boundary

A job screen answers one question: **is this opportunity worth more of the
user's time?** It precedes posting capture, formal matching, vault hydration,
resume tailoring, and critique.

The screen is read-only by default. Research findings describe the employer or
opportunity; they never become candidate facts.

## Match decision

Use the shared grading contract under
`../match-job/references/grading-contract.md`. Build the transient criterion
matrix from the material requirements and demonstrated resume evidence, then
run `resume-builder match classify`. Its fixed label controls the `Match` line.
Do not upgrade that label because the resume is polished, the candidate has
transferable potential, or exact terms happen to be present.

Classify only material posting requirements before choosing the label:

- **Mandatory and role-defining** — central to the role's daily work and stated
  as a minimum; absence creates an eligibility risk.
- **Mandatory but substitutable** — required, but the posting or a reliable
  opportunity-specific source explicitly permits equivalent tools, education,
  or experience.
- **Supporting** — important to performance but not an apparent eligibility
  gate.
- **Preferred** — a differentiator rather than a minimum.
- **Lifestyle constraint** — location, schedule, travel, on-call, employment
  type, or compensation that could independently make the job unsuitable.

Then decide in this order:

1. If the posting is materially incomplete or known candidate sources are
   unavailable or unfinished, use **Unknown match** and ask a targeted question
   when one could resolve it. Do not use **Unknown match** merely because a
   completed evidence search does not establish a stated requirement; treat
   that requirement as unsupported.
2. If a mandatory and role-defining requirement is unsupported and no accepted
   substitution is stated, use **Weak match**. Keep adjacent experience under
   `Strongest overlap`; do not let it satisfy the eligibility gate.
3. Otherwise judge the breadth of demonstrated core work and choose exactly one
   label:
   - **Strong match** — the closest resume visibly proves most core requirements,
     including every clearly role-defining minimum; only prioritization or light
     tailoring appears necessary.
   - **Partial match** — most core work is demonstrated, the remaining material
     gaps are limited and credibly bridgeable, and no unsupported,
     non-substitutable role-defining minimum remains.
   - **Weak match** — several independent core capabilities are absent, or the
     demonstrated work is substantially misaligned, even when some transferable
     overlap exists.
   - **Unknown match** — the posting, vault, or registered source material lacks
     enough information for a defensible classification.

Treat related terms as capability clusters rather than separate gaps. Do not
count missing keywords, use a fixed number of gaps as an automatic threshold,
or assume that tools in the same category are equivalent. One unsupported
role-defining minimum can justify **Weak match**; several missing preferences
may not. Accept a substitution only when the posting or a reliable source tied
to the opportunity permits it. Do not invent percentages, points, or a
universal score.

Use these boundary cases to calibrate judgment:

| Scenario | Expected label |
|---|---|
| Required primary-platform tenure is unsupported and no substitution is permitted | **Weak match** |
| Several related tool terms are absent, but an accepted equivalent capability is demonstrated | **Partial match** |
| Material experience may exist, but the posting or candidate evidence is incomplete | **Unknown match** |
| Every role-defining minimum and most core work are visibly demonstrated | **Strong match** |

Do not call the match an ATS score. ATS visibility is one part of the `Match`
field and must distinguish missing wording from missing evidence.

## Required output

Stay within roughly 350 words and one rendered page. Use this order and do not
add sections unless the user asks:

```markdown
## <Actual company or Undisclosed Client> — <Role>

**Match: <fixed match label>**

**Closest resume:** <name or none>

**Strongest overlap:** <one short line with no more than three demonstrated strengths>

**Primary gap:** <the most decision-relevant evidence, requirement, or lifestyle gap; use None when there is no material gap>

**ATS visibility:** <important terms/evidence already visible and the few material items missing or under-demonstrated>

| | |
|---|---|
| **Company** | <actual employer/client and integer years in business, or Undisclosed> |
| **Recruiter** | <include only for a staffing intermediary: name, integer years in business, and intermediary relationship> |
| **Employment** | **<Remote, Hybrid, or On-site> · <Full-time, Part-time, or Contract>** |
| **Pay** | <use the matching compensation format below> |
| **Benefits** | <posting-confirmed benefits or Not specified> |

### Career direction

<At most two short sentences: when this advances the user's direction and when
it does not.>

### What could improve the match

<Zero to three numbered questions. Ask only questions that could change the
match, next action, or add material reusable evidence. Omit this section when
no question meets that bar.>

<One final sentence naming the immediate next action.>
```

## Compression rules

- Title the screen with the actual employer or client. If a staffing
  intermediary does not disclose the client, title it `Undisclosed Client` and
  set `Company` to `Undisclosed`; never title the screen with the intermediary.
- Show age as an integer number of years in business for consistency; never
  show only `founded in <year>`. Calculate years from the supported founding
  year and the current year.
- Add `Recruiter` only when a recruiter or staffing intermediary is involved.
- Keep `Employment` to the work arrangement and employment type. Move
  unresolved contract, location, schedule, on-call, or travel details into a
  targeted question only when they could change the match or next action.
- Preserve the compensation basis used by the posting:
  - for annual compensation, show only `**Annual:** <confirmed range>`;
  - for hourly compensation, show `**Hourly:** <confirmed range>` and optionally
    `**Annualized equivalent:** <calculated range>` when the comparison is useful;
  - when the posting states both, show both without converting either one;
  - when compensation is absent, show `**Compensation:** Not specified`.
- Always place `Benefits` immediately after `Pay` as its own table row. When
  job-specific benefits are absent, show `Not specified`.
- Do not derive or display an hourly rate from annual compensation. Any
  annualized equivalent derived from hourly compensation must be clearly
  identified as an estimate, not guaranteed salary.
- Report benefits as confirmed only when the posting or another source tied to
  the specific opportunity states them. A staffing firm's general consultant
  FAQ does not establish benefits for the job; use `Not specified` instead.
- Put `Match` before company, employment, and pay so the user's fit is the first
  substantive answer.
- Keep the closest resume, strongest overlap, primary gap, and ATS visibility
  directly beneath `Match` as short bold-labeled lines; never turn them into a
  criterion table or standalone sections.
- Do not add a separate recommendation field. Express the practical decision
  once in the final next-action sentence, grounded in the match and unresolved
  questions.
- Never create a section titled “Is this a stretch?”
- Include no more than three strongest overlaps and three material gaps.
- Link sources inline without a separate bibliography.
- Do not explain the screening method, deterministic audit, evidence-status
  taxonomy, or every researched fact.
- End with one specific next action rather than a generic recommendation label.

## Research judgment

Prefer current official sources for company identity, employment programs, and
job-specific benefits. Use independent review or compensation sources as
directional signals and state their limitations. When a staffing intermediary
represents an undisclosed client, the client's culture, manager, workload, job
security, and benefits remain unknown even if the intermediary has favorable
reviews or advertises benefits for some consultants.
