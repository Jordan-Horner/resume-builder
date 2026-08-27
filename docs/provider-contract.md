# Provider contract

Every provider exposes a stable `name`, a unique `source_key`, and `fetch(since) -> ProviderResult`.

A provider must:

- translate source payloads into `JobObservation` without leaking its native types;
- retain a stable external job ID when available;
- preserve raw payload data for diagnostics;
- return explicit failure rather than silently converting an exception to a successful empty result;
- mark `suspicious_empty` when a normally productive source returns nothing;
- set `authoritative_complete` only when the result is a complete active-board snapshot suitable for lifecycle checks;
- treat `since` as a retrieval bound only when the source actually honors it.
- report retrieval and filtering metrics when the provider applies local eligibility rules.

## Work-arrangement contract

Providers normalize work arrangements into `remote`, `hybrid`, `onsite`, or `unknown`. `unknown` means the source
did not provide enough evidence; a false or missing legacy `remote` flag is never proof of onsite work. A posting
may advertise multiple valid arrangements, and providers must preserve that set when the source exposes structured
location-level workplace types.

Structured provider fields take priority and must retain their field name, provider, and matched value as evidence.
When no structured value exists, the shared classifier may use the displayed location or explicit scheduling
phrases in the description. It deliberately does not classify bare title phrases such as `hybrid cloud` or
`remote support`. Canonical jobs inherit the complete mode set from their preferred observation; all observation
evidence remains available for auditing even when another provider becomes preferred.

The inventory persists observation modes and their evidence in `observation_work_modes`, and the canonical mode
set in `job_work_modes`. The legacy `jobs.work_mode` column is a display projection: one mode is stored directly,
multiple modes appear as `mixed`, and no evidence appears as `unknown`.

Commercial-board results are discovery observations and never authoritative for closure. Direct ATS list results
may be authoritative when pagination completes successfully. JazzHR and Rippling list every public opening first,
then fetch details only for locally matching titles; their normal filtered runs are therefore not authoritative
whole-board snapshots.

Direct ATS boards are kept in a separate private registry. Discovery reads only commercial-source application URLs
already present in active inventory, recognizes known public ATS URL shapes, and writes new entries disabled. Registry tags are inert
metadata reserved for reusable company profiles such as a future FAANG+ view. When an ATS adapter applies title,
remote, or freshness eligibility to a complete board response, it must not claim that the filtered subset is an
authoritative whole-board snapshot.

## Commercial-board title queries

Search families contain semantic title aliases, not raw provider syntax. A commercial-board adapter must compile
those aliases for its tested transport. LinkedIn receives one Boolean query per enabled family. Although
Indeed.com documents Boolean and `title:` expressions, the GraphQL route used by the pinned JobSpy adapter can
return a generic fallback page for those expressions. Indeed therefore receives one plain query per title, such
as:

```text
site reliability engineer
SRE
cloud engineer
```

Indeed requests may be spaced with `request_delay_seconds`, then merged and deduplicated. Local title matching is
required because Indeed's keyword search also considers descriptions. It uses complete normalized phrases, so
`SRE` matches `Cloud SRE` but not a larger unrelated token. Provider-side remote filters are preferred. When
Indeed is remote-only, freshness is applied locally because its JobSpy transport cannot combine the two server
filters. Indeed's date-only publication value is compared at calendar-date precision so an intra-day checkpoint
cannot discard a same-day posting.

`family_results_wanted` can increase the qualified-candidate target for a noisy or high-priority family without
multiplying the cost of every search. LinkedIn continues card pagination until it reaches this target or
`max_cards_scanned`. Exhausting the scan limit increments `saturated_queries`; this is a coverage warning, not a
scrape failure.

LinkedIn uses the logged-out guest search and detail fragments directly. The search adapter advances the absolute
`start` offset by ten, stops on empty, short, or repeated pages, and never treats partial discovery as an
authoritative active-board snapshot. Cards are deduplicated and locally title- and freshness-gated before detail
requests. Because guest results rotate, incremental runs retain a configurable minimum rolling lookback instead of
treating completion time as a complete chronological cursor. In remote-only mode, the adapter uses one of three
policies: `strict` requires role-specific evidence, `balanced` also accepts employer-level remote evidence, and
`source` trusts LinkedIn's filter unless contradicted. Language such as “remote hands,” required office presence,
one remote day, hybrid schedules, onsite, or in-office is rejected in every mode. Accepted observations record the
evidence rule, source, and matching text.

Successful LinkedIn details are cached by provider job ID and parser version. Cache failures are surfaced as partial
run errors without discarding retrieved jobs. A missing detail is skipped; an individual parser failure is recorded
and processing continues; authentication, challenge, forbidden, rate-limit, and provider-wide transport failures
stop further requests. Partial and failed runs never advance the checkpoint.

LinkedIn uses `linkedin:guest` as its source key while retaining `linkedin` as the provider and the numeric LinkedIn
job ID as the observation identity. Replacing the former `jobspy:linkedin` source therefore starts a fresh
checkpoint without duplicating existing observations. HTTP 401, 403, and 429 responses stop the provider and make
the run unsuccessful; failed runs do not advance the checkpoint.

Canonical inventory may merge observations only on an exact canonical URL or the combination of exact normalized
company, exact normalized title, and exact non-empty description hash. The latter merge reason is
`exact_company_title_description`; fuzzy title similarity remains review-only.

Verified Greenhouse short-link redirects are stored as durable URL aliases. Workday syndicated copies may also
merge on an exact requisition ID embedded in the commercial application URL when normalized company and title both
agree and the match identifies one canonical job. Both paths retain every observation; neither permits fuzzy
company/title-only consolidation.

Commercial-board metrics include the query count, raw result count, invalid rows, title rejections, remote
rejections, freshness rejections, pre-deduplication acceptance, duplicates, and final acceptance. Family- and
query-level raw and pre-deduplication counts are included in the persisted metrics payload.
