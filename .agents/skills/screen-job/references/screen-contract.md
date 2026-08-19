# Job Screen Contract

## Purpose and boundary

A job screen answers one question: **is this opportunity worth more of the
user's time?** It precedes posting capture, formal matching, vault hydration,
resume tailoring, and critique.

The screen is read-only by default. Research findings describe the employer or
opportunity; they never become candidate facts.

## Match decision

Choose exactly one match label:

- **Strong match** — the closest resume visibly proves most core requirements;
  only prioritization or light tailoring appears necessary.
- **Partial match** — meaningful direct or transferable evidence exists, but
  one or two material requirements, stories, or visibility problems remain.
- **Weak match** — the core work or required evidence is substantially absent
  or misaligned.
- **Unknown match** — the posting or vault lacks enough information for a
  defensible classification.

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
| **Pay** | **Hourly:** <confirmed range or Not specified><br>**Annual equivalent:** <calculated range or Not available><br>**Benefits:** <posting-confirmed benefits or Not specified in the posting> |

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
- Structure `Pay` as separate Hourly, Annual equivalent, and Benefits lines.
  Annualize hourly compensation when useful and clearly treat it as an
  equivalent, not guaranteed salary.
- Report benefits as confirmed only when the posting or another source tied to
  the specific opportunity states them. A staffing firm's general consultant
  FAQ does not establish benefits for the job; use `Not specified in the
  posting` instead.
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
