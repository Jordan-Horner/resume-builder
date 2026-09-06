# Resume Builder

[![CI](https://github.com/Jordan-Horner/resume-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/Jordan-Horner/resume-builder/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
[![Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**A private, evidence-grounded workspace for building resumes and managing a
job search.**

> **Your career is bigger than two pages.** What matters most changes with each
> opportunity, so tailor every resume while preserving the rest of your story.

Resume Builder turns old resumes, LinkedIn exports, and career notes into a
versioned career vault. It uses that evidence to create targeted resumes,
aggregate and screen job opportunities, track applications, and support the
workflow through a local web portal and bounded AI agent.

The central design constraint is simple: AI can help interpret, select, and
phrase information, but it cannot silently invent career facts, strengthen
authorship, discard opportunities, or take consequential actions on the user's
behalf.

> **Project status:** The resume lifecycle, multi-source job discovery, local
> portal, AI-assisted screening, Gmail tracking, scheduled automation, and
> private Telegram access are implemented. Automatic job submission is
> intentionally out of scope today.

## Capabilities

| Area | What is implemented |
|---|---|
| Career evidence | Imports multiple source documents into a Git-versioned vault with stable fact IDs and provenance. |
| Resume building | Creates directional and job-tailored resumes, checks evidence grounding and ATS readability, publishes a reviewable preview, and mints a PDF only after approval. |
| Job aggregation | Collects from LinkedIn, Indeed, and direct Greenhouse, Lever, Ashby, SmartRecruiters, and Workday boards; preserves source observations and conservatively deduplicates canonical jobs. |
| Job review | Provides persistent search, date, location, work-mode, employment-type, compensation, and clearance filters without deleting the underlying inventory. |
| Screening | Combines deterministic eligibility checks with criterion-by-criterion, evidence-cited semantic fit analysis, including worthwhile stretch roles, local abstention when retrieval is too weak, and an offline human-review calibration workflow. |
| Applications | Records append-only application history, pins the resume used, and can reconcile confident stage changes through read-only Gmail access. |
| Automation | Runs scheduled discovery, optional background quick screens, Gmail reconciliation, and low-noise notifications in a self-hosted container. |
| Career agent | Answers workspace questions, discusses a selected job or resume, runs bounded screens, and proposes review-gated resume wording or lifecycle changes. |

## Local portal

The responsive React portal brings the end-to-end workflow into one private
interface:

- **Jobs** combines every enabled source into one review queue. Filters persist
  locally and can be reset to saved search preferences or cleared for broader
  exploration. Job detail includes source links, compensation, a matching
  resume recommendation, and an on-demand quick screen.
- **Applications** shows current stages, event history, and the exact resume
  associated with an application when one was recorded.
- **Resumes** renders active directional and tailored resumes from their
  canonical Markdown sources and supports reversible retirement.
- **Skills** surfaces confirmed vault evidence and lets the user select a
  bounded set of skills to broaden future searches.
- **Settings** manages search preferences, job sources, scrape schedules,
  blocked companies, integrations, and appliance health.

The first-run flow accepts PDF, DOCX, Markdown, HTML, and text sources, suggests
target roles from verified excerpts when an AI provider is connected, and
guides the user through location, work mode, and compensation preferences.
If a draft is weak, the agent checks your saved career evidence and imported sources
before asking a small number of targeted questions; it does not invent stronger claims.

## Agent with controlled actions

The portal includes a persistent, context-aware assistant. A job or resume is
attached explicitly rather than inferred from navigation, so the user can see
what the agent is working on. The agent can:

- explain the current job queue and discuss a selected opportunity;
- run the same bounded, cached job screen used by the portal;
- propose a wording-only resume edit as a before/after decision;
- propose retiring or restoring a directional resume; and
- interact through the portal, console, or an allowlisted private Telegram
  channel.

Writes use explicit proposal cards and existing review services. Accepted
wording is checked for factual equivalence, compiled, independently reviewed,
and sent through the normal preview pipeline. Factual enrichment, permanent
deletion, minting, and application submission are not exposed as agent write
tools.

```text
Portal · CLI · Telegram
          ↓
   Bounded career agent
          ↓
Resumes · Jobs · Gmail · Applications
          ↓
  Private, versioned workspace
```

See [Portal assistant](docs/portal-assistant.md) and
[Agent architecture](docs/agent.md) for the tool and approval boundaries.

## How the resume workflow works

1. **Capture evidence.** Register source resumes, exports, and notes while
   retaining provenance.
2. **Build the vault.** Store approved facts independently from any one resume.
3. **Choose a target.** Select a career direction or preserve a real posting.
4. **Plan and draft.** Select coherent career stories from supported evidence.
5. **Review.** Check language, fit, retrieval, authorship, and structural losses.
6. **Preview and mint.** Let the user review the current result, then enforce
   page, rendering, grounding, and text-extraction gates before PDF release.

```text
Source material → Career vault → Targeting → Review → Resume
```

The vault remains the durable record. Resumes are focused views of that record,
not competing copies of a manually maintained “master resume.”

## Quick start

**Requires:** Python 3.11 or newer, Node.js 22 for the frontend, and Playwright
Chromium for PDF verification. OpenRouter, Gmail, Telegram, and Discord are
optional integrations.

```bash
git clone https://github.com/Jordan-Horner/resume-builder.git
cd resume-builder
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m playwright install chromium
resume-builder
cd web && npm install && npm run build && cd ..
resume-builder-web
```

The guided command creates a separate private workspace and walks through the
initial setup. Then open `http://127.0.0.1:8765`; the server discovers that
workspace and serves the production frontend from `web/dist`.

From the portal, CLI, or agent, you can ask naturally:

```text
Build a Support Operations resume from my career history.
Screen this job: <posting URL>
Tailor my closest resume to this job description.
Show me new jobs I have not reviewed.
```

For frontend development, run `npm run dev` in `web`; `/api` requests proxy to
the local FastAPI server. For an always-on single-container deployment, see
[Container deployment](docs/container-deployment.md).

The CLI remains available for advanced and agent-driven workflows:

```bash
resume-builder                           # state-aware guided entry point
resume-builder jobs new                  # show unseen inventory
resume-builder jobs screen <job-id>      # screen one preserved posting
resume-builder application report        # show application history
resume-builder preview <resume.md>        # publish a reviewed preview
resume-builder mint <resume.md>           # release the approved PDF
```

## Architecture and engineering choices

![Resume Builder architecture](docs/assets/architecture.png)

Resume Builder is built as a local-first Python application with a React 19 and
TypeScript frontend. FastAPI exposes the portal API; Pydantic and structured
model responses enforce boundaries; SQLite stores generated inventory and
runtime state; Markdown and Git remain authoritative for durable career data.

Notable engineering decisions include:

- deterministic validation around probabilistic AI judgment;
- provider- and channel-neutral agent adapters;
- typed contracts across Python and TypeScript boundaries;
- source-level job provenance and conservative cross-provider deduplication;
- append-only application events and immutable submitted-resume snapshots;
- idempotent imports, scans, cached screens, and notification delivery;
- lazy-loaded responsive frontend routes with accessibility-focused interaction;
- content-limited logs and external secret storage;
- AMD64 and ARM64 container builds with SBOM and provenance attestations; and
- Python, frontend, browser, architecture, package-boundary, and secret checks
  in CI.

Read [Architecture](docs/architecture.md) and
[Design decisions](docs/design-decisions.md) for the deeper system boundaries.

## Privacy and safety model

The reusable engine and personal career workspace are separate repositories:

```text
resume-builder/             Public or reusable engine
private-workspace/          Separate private Git repository
├── vault/                  Sources and approved career facts
├── directions/             Target-role profiles
├── job-search/             Inventory configuration and preferences
├── applications/           Append-only application history
├── targets/                Preserved job postings
└── resumes/                Editable resume sources
```

Personal data, credentials, email content, and generated career artifacts stay
out of the public engine repository. Gmail uses Google's official read-only API;
message bodies are processed in memory and are not written to the engine,
workspace, runtime database, or logs. Model calls use bounded payloads and
require the configured authorization policy before private data leaves the
workspace.

The portal is designed for a single user on a trusted device or private network.
It is not a multi-tenant authentication boundary and should not be exposed
directly to the public internet.

## Fictional demo

The included Phoenix Wright fixture demonstrates the preservation model without
using real candidate data. Strong evidence is surfaced, limited ownership stays
limited, adverse history is preserved without being marketed, and unresolved
claims remain held for review.

[![Phoenix Wright evidence flows from a career vault through targeting decisions into a focused resume](docs/assets/phoenix-demo-flow.svg)](examples/phoenix-wright/README.md)

Explore the [complete fictional case study](examples/phoenix-wright/README.md) or
the shorter [demo walkthrough](docs/demo.md).

## Documentation

| Topic | Guide |
|---|---|
| System boundaries | [Architecture](docs/architecture.md) |
| Portal and job filters | [Frontend design](docs/frontend-design-plan.md) |
| Agent and OpenRouter | [Agent architecture](docs/agent.md) |
| Portal assistant | [Assistant behavior](docs/portal-assistant.md) |
| Job collection | [Job puller](docs/job-puller/README.md) |
| Inventory and deduplication | [Job inventory integration](docs/job-inventory-integration.md) |
| Gmail setup and privacy | [Gmail automation](docs/gmail-automation.md) |
| Scheduling and containers | [Automation](docs/automation.md) |
| Deployment and updates | [Container deployment](docs/container-deployment.md) |

## Contributing

Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change and
[SECURITY.md](SECURITY.md) to report a vulnerability or privacy concern. Use
fictional or redacted examples in public issues—never attach a real resume,
contact details, credentials, or private job-search information.

Resume Builder is available under the [Apache License 2.0](LICENSE).

<details>
<summary>Contributor checks</summary>

```bash
pytest
ruff check src tests scripts .agents/skills/hydrate-vault/scripts
ruff format --check src tests scripts .agents/skills/hydrate-vault/scripts
mypy src
python -m build
python scripts/audit_distribution.py
python scripts/check_architecture.py
cd web && npm test && npm run build
```

</details>
