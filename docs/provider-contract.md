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

Commercial-board results are discovery observations and never authoritative for closure. Direct ATS list results may be authoritative when pagination completes successfully.

