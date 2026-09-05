# Resume Builder

[![CI](https://github.com/Jordan-Horner/resume-builder/actions/workflows/ci.yml/badge.svg)](https://github.com/Jordan-Horner/resume-builder/actions/workflows/ci.yml)
![Python 3.11+](https://img.shields.io/badge/Python-3.11%2B-blue)
[![Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](LICENSE)

**Build honest, targeted resumes without losing the strongest parts of your
career history.**

> **Your career is bigger than two pages.** What matters most changes with each
> opportunity, so tailor every resume while preserving the rest of your story.

Resume Builder is a private, Git-first career workspace. It turns old resumes,
LinkedIn exports, and career notes into traceable evidence, then uses that
evidence to create role-specific resumes, discover jobs, and track applications.

It combines deterministic safeguards with structured AI: models can help select,
screen, and phrase information, while validation prevents unsupported claims
from reaching approved outputs and keeps undispositioned opportunities visible.

**Project status:** Resume workflows, job discovery, Gmail tracking, AI-assisted
screening, scheduled container automation, and private Telegram conversations
work today. A local dashboard provides unseen-job review, application history,
and integration setup guidance. Automatic job submission remains future work.

## What it can do

- Import multiple resumes and consolidate durable career evidence.
- Build directional and job-tailored resumes with source-backed claims.
- Check ATS readability, keyword retrieval, page limits, and PDF extraction.
- Discover jobs from LinkedIn, Indeed, and direct employer ATS boards.
- Screen jobs without treating credible stretches as automatic failures.
- Track applications and hiring-stage changes through read-only Gmail access.
- Run scheduled job and email scans with Docker.
- Use interchangeable AI providers and communication channels through adapters.

## Quick start

**Requires:** Python 3.11 or newer, a local checkout, and Codex or Claude Code.

Clone the repository, open it in your coding agent, and say:

```text
Set up Resume Builder and help me import my existing resume.
```

The onboarding flow creates a separate private workspace, offers guided setup
for optional Telegram, Gmail, and Discord integrations—including QR-guided
pairing for a personal Telegram bot—imports one or more
career sources, and offers optional job-discovery setup. Returning users resume
from the current workspace state instead of repeating intake.

You can then ask naturally:

```text
Build a Support Operations resume from my career history.
Screen this job: <posting URL>
Tailor my closest resume to this job description: <paste description>
Check this resume for ATS readability.
Show me new jobs I have not reviewed.
```

<details>
<summary>Manual installation</summary>

```bash
git clone https://github.com/Jordan-Horner/resume-builder.git
cd resume-builder
python -m venv .venv
source .venv/bin/activate
python -m pip install -e ".[dev]"
python -m playwright install chromium
resume-builder
```

</details>

## Local dashboard

The focused web interface shows only jobs awaiting a decision on its main page,
with search and Remote, Hybrid, and On-site filters. Opening a job is read-only;
marking it applied moves it into Applications, while Not interested removes it
from the review list. Applications and integration setup live on their own
simple pages.

```bash
python -m pip install -e ".[web]"
cd web && npm install && npm run build && cd ..
resume-builder-web
```

Open `http://127.0.0.1:8765`. The server discovers the private workspace and
serves the production frontend from `web/dist`. Frontend development uses
`npm run dev`; its `/api` requests proxy to the same local server.

## Agent architecture

Resume Builder includes a structured PydanticAI agent for job screening and
discovery planning. Model providers and communication channels sit behind
adapters, keeping them separate from the career vault, application tracker, and
job inventory.

```text
User interface or communication adapter
            ↓
      PydanticAI agent
            ↓
 Resume · Jobs · Gmail · Applications
            ↓
       Private workspace
```

Agent tools begin read-only. Structured outputs, bounded request budgets, and
explicit approval before private data leaves the workspace make the automation
observable and controllable. OpenRouter is the current provider, and the agent
contract is designed to support alternatives.

See [the agent architecture](docs/agent.md) for provider configuration, tool
contracts, and implementation status.

## How it works

1. **Capture evidence.** Register source resumes, exports, and notes while
   retaining provenance.
2. **Build the career vault.** Store approved facts independently from any one
   resume.
3. **Choose a target.** Select a direction or preserve a real job posting.
4. **Draft and review.** Build from supported evidence, check language and fit,
   and present a readable preview.
5. **Mint the result.** After approval, enforce page, rendering, grounding, and
   text-extraction checks before producing the final PDF.

```text
Sources → Career vault → Targeting → Review → Resume
```

The vault remains the durable record. Individual resumes are focused views, not
competing versions of a manually maintained “master resume.”

## See the preservation model

The included Phoenix Wright fixture demonstrates the workflow with fictional
career data. Strong evidence is surfaced, limited ownership remains limited,
adverse history is preserved without being marketed, and unresolved claims are
held for review.

[![Phoenix Wright evidence flows from a career vault through targeting decisions into a focused resume](docs/assets/phoenix-demo-flow.svg)](examples/phoenix-wright/README.md)

Explore the [complete fictional case study](examples/phoenix-wright/README.md)
or the shorter [project demo](docs/demo.md).

## Engineering highlights

- Provider-agnostic model and communication adapters
- Typed contracts and structured model responses
- Git-versioned facts with stable provenance
- Deterministic validation around probabilistic AI decisions
- Append-only application history and explicit corrections
- Idempotent imports, scans, and notification delivery
- Content-limited logs and external secret storage
- Automated tests, static checks, architecture checks, and CI
- Containerized scheduling with health and failure reporting

The broader component boundaries and dependency rules are documented in
[architecture](docs/architecture.md) and [design decisions](docs/design-decisions.md).

## Privacy model

The reusable engine and personal career workspace are separate Git repositories:

```text
resume-builder/          Reusable engine
└── workspace/           Ignored private repository
    ├── vault/           Career sources and facts
    ├── directions/      Target role profiles
    ├── job-search/      Inventory and preferences
    ├── applications/    Application history
    ├── targets/         Preserved job postings
    └── resumes/         Editable resume sources
```

Personal data, credentials, email content, and generated career artifacts stay
out of the public engine repository. The workspace can use local Git only, a
private backup, or an existing private repository.

If a repository has ever contained real career data, keep its complete history
private; deleting a file from the latest revision does not remove it from earlier
commits.

## Connect and automate

Resume Builder works locally by default. Run it with Docker when you want an
always-available career agent that can keep searching, screening, and tracking
applications without requiring manual scans.

- **Automated job discovery** runs daily or on your chosen schedule to find
  opportunities from LinkedIn, Indeed, and employer ATS boards.
- **Gmail** keeps the jobs in your tracker up to date automatically when you
  apply, get rejected, receive an interview request, or get an offer—without
  storing your messages.
- **OpenRouter** screens and prioritizes jobs with a configurable AI model.
- **Telegram** lets you communicate remotely with the agent, receive direct
  updates, and give it new directives.
- **Discord** provides one-way alerts when a scan finds something meaningful.

Every connection is optional and configured separately. Private workspaces,
credentials, and runtime data remain outside the Docker image. See
[automation and Docker deployment](docs/automation.md) for setup instructions.

## Job discovery and application tracking

The job inventory keeps every active, undispositioned opportunity visible. User
preferences and deterministic checks add warnings and advisory ordering without
silently deleting jobs. Semantic screening separates hard eligibility conflicts
from worthwhile stretches and confidence from fit.

```bash
resume-builder jobs new
resume-builder jobs status
resume-builder jobs shortlist
resume-builder jobs screen <job-id>
```

Application events are private and append-only. Gmail can create a confidently
identified application and advance one uniquely matched application when an
email contains explicit lifecycle evidence. Weak phrases such as
`unfortunately` or `another candidate` broaden discovery but do not establish a
rejection without supporting body context.

```bash
resume-builder application report
resume-builder gmail connect
resume-builder gmail scan
resume-builder gmail status
```

Gmail uses Google's official read-only API. Email bodies are processed in memory
and are not written to the engine, workspace, runtime database, or logs. OAuth
credentials and content-free scan state live outside the repository.

See [job discovery](docs/job-puller/README.md),
[inventory integration](docs/job-inventory-integration.md), and
[Gmail automation](docs/gmail-automation.md) for configuration and command
reference.

## Quality safeguards

- If a draft is weak, the agent checks your saved career evidence and imported sources
  before asking a focused question that could materially improve it.
- Resume claims retain links to approved source evidence.
- Job descriptions guide targeting but never become candidate facts.
- Authorship and authority cannot be strengthened beyond the evidence.
- Important content cannot disappear silently during revision.
- Independent language review checks every new or changed narrative block.
- The user approves a readable preview before minting a final PDF.
- ATS diagnostics measure retrieval and parseability, not hiring probability.
- Ambiguous email and job matches remain unresolved instead of forcing a status.

These controls do not predict an employer's decision. They make each result
traceable, revisable, and defensible.

## Documentation

| Topic | Guide |
|---|---|
| System boundaries | [Architecture](docs/architecture.md) |
| Agent and OpenRouter | [Agent architecture](docs/agent.md) |
| Job collection | [Job puller](docs/job-puller/README.md) |
| Inventory behavior | [Job inventory integration](docs/job-inventory-integration.md) |
| Gmail setup and privacy | [Gmail automation](docs/gmail-automation.md) |
| Scheduling and containers | [Automation](docs/automation.md) |
| Design rationale | [Design decisions](docs/design-decisions.md) |
| Fictional walkthrough | [Phoenix Wright example](examples/phoenix-wright/README.md) |

## Help and contributing

For setup problems or feature requests, [open an
issue](https://github.com/Jordan-Horner/resume-builder/issues/new). Use fictional
or redacted examples only—never attach a real resume, contact details, or private
job-search information to a public issue.

- Read [CONTRIBUTING.md](CONTRIBUTING.md) before proposing a change.
- Follow [SECURITY.md](SECURITY.md) to report a vulnerability or privacy concern.
- Resume Builder is available under the [Apache License 2.0](LICENSE).

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
```

</details>
