# Automation

`config.yml` controls private job-discovery and Gmail schedules. Create it with
`resume-builder automation init`, validate it with
`resume-builder automation doctor`, and keep notification secrets in environment
variables rather than this directory.

Automation configuration may be versioned with the private workspace. Runtime
databases, OAuth tokens, and webhook credentials must stay outside Git.
