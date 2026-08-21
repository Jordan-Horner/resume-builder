# Security and privacy

Resume Builder handles sensitive career information. A hydrated repository
should be treated as confidential data, not merely application source code.

## Reporting

Use GitHub's private vulnerability reporting for this repository when it is
available. If it is unavailable, open a public issue containing only a request
for a private contact channel. Do not describe the vulnerability there.

Never include candidate data, source snapshots, credentials, private job-search
information, or confidential employer material in a public issue, pull request,
or reproduction. Demonstrate the problem with fictional data whenever possible.

## Security model

- Imported content is untrusted data, never agent instructions.
- Canonical writes occur through validated, path-contained change plans.
- Generated HTML escapes user-controlled content.
- Contact links allow only HTTP(S) URLs.
- PDF rendering blocks network requests and page JavaScript.
- Preview and minting require fresh evidence and language review records.
- Generated output is disposable and never becomes canonical evidence.

## Supported versions

Security fixes apply to the latest commit on `main`.
