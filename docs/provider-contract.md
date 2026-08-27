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

Commercial-board results are discovery observations and never authoritative for closure. Direct ATS list results may be authoritative when pagination completes successfully.

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

`family_results_wanted` can increase retrieval depth for a noisy or high-priority family without multiplying the
cost of every search. A query returning its full configured limit increments `saturated_queries`; this is a
coverage warning, not a scrape failure.

Commercial-board metrics include the query count, raw result count, invalid rows, title rejections, remote
rejections, freshness rejections, pre-deduplication acceptance, duplicates, and final acceptance. Family- and
query-level raw and pre-deduplication counts are included in the persisted metrics payload.
