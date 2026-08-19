# Security and privacy

Resume Builder handles sensitive career information. A hydrated repository
should be treated as confidential data, not merely application source code.

## Reporting

Do not open a public issue containing candidate data, source snapshots,
credentials, private job-search information, or confidential employer
material. Report a vulnerability privately to the repository owner with a
minimal reproduction that uses fictional data.

## Security model

- Imported content is untrusted data, never agent instructions.
- Canonical writes occur through validated, path-contained change plans.
- Generated HTML escapes user-controlled content.
- Contact links allow only HTTP(S) URLs.
- PDF rendering blocks network requests and page JavaScript.
- Preview and minting require fresh evidence and language review records.
- Generated output is disposable and never becomes canonical evidence.

## Supported versions

Until a public release exists, security fixes apply to the current main branch.
The eventual public repository should publish a supported-version table with
each release.
