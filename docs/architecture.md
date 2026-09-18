# Architecture

![Resume Builder architecture](assets/architecture.png)

Resume Builder is a local-first application for maintaining a private career
record and producing targeted resumes from it. Its central rule is simple:
career history is stored separately from the documents created from that
history.

This separation allows a person to create several resumes without copying,
silently changing, or inventing career details. Imported documents provide
evidence. Reviewed career claims become the facts the system is allowed to use.
Resumes, previews, and PDFs are generated from those facts.

AI may help organize evidence, draft prose, and evaluate a resume. It is never
treated as a factual source and cannot approve its own work.

## A resume claim from import to PDF

Consider a fictional example in which an imported resume says:

> Reduced support response time by 30% after introducing a new triage process.

The claim moves through the system as follows:

1. The imported file is preserved as a source snapshot. It is evidence, not yet
   accepted truth.
2. The claim is reviewed for accuracy, scope, authorship, and conflicts with
   other sources.
3. If accepted, it becomes a **canonical fact**: the system's reviewed record
   of one career claim, including a link back to its source.
4. A role direction or specific job posting may make that fact relevant to a
   resume.
5. A **synthesis plan** records why the fact was selected, how it supports the
   intended hiring story, and what other evidence was left out.
6. The editable resume is written in Markdown and cites the fact internally.
7. Automated checks confirm that the citation exists and that the wording does
   not exceed the evidence. Independent review evaluates the visible prose.
8. The reviewed resume is published as a web preview. An explicit mint request
   releases that exact preview as a checked PDF.

This pattern applies to every visible resume claim. A job posting can make the
claim more or less relevant, but it cannot create or strengthen the claim.

## Major parts of the system

### Career evidence

Imported resumes, LinkedIn exports, and career notes are preserved as source
material. They may contain conflicts, outdated wording, or unsupported claims.
The system therefore keeps them unchanged and treats them as proposals rather
than truth.

Reviewed claims are stored one per Markdown file in the private career vault.
Each fact records where it came from and whether it is confirmed or still needs
review. Conflicts remain visible until they are resolved. These canonical facts
are the only factual source available to future resumes.

### Role directions and job postings

A direction describes a reusable type of role, such as support operations or
incident management. A preserved job posting describes one real opportunity.
Both tell the system what to emphasize and what an employer may require.

Directions and postings are targeting information, not candidate evidence. If
a posting asks for Kubernetes experience, that requirement does not prove the
candidate has Kubernetes experience.

### Resume planning

Before writing a substantial resume, the system creates a versioned synthesis
plan. The plan connects the target role to relevant career facts, groups facts
into coherent stories, and records intentional omissions. It also defines the
purpose of the summary and the role each experience entry plays in the overall
hiring argument.

Planning happens before prose so evidence selection can be inspected separately
from writing quality.

### Resume documents

The editable resume source is evidence-annotated Markdown under `resumes/`.
Visible claims cite canonical fact IDs in hidden comments. The compiler checks
those citations and creates the data needed to render the resume.

Compiled JSON, web previews, and PDFs are generated artifacts. They may be
deleted and rebuilt; they must never be edited as if they were source files.

### Review and publishing

Every new or changed narrative block receives an independent language review.
The reviewer sees the visible resume but not the builder's private rationale, so
it can judge whether the wording works for a reader encountering it cold.

Some resumes also receive a deeper review of evidence selection and hiring
position. The system chooses that path based on the current resume and plan;
passing automated checks alone is never presented as editorial approval.

The web preview is the approval surface. If a resume, cited fact, template, or
applicable feedback rule changes, the old preview becomes out of date. Minting
requires an explicit request and releases only the current preview after PDF
layout and text-extraction checks pass.

### Jobs and applications

Job collection stores public postings in a reviewable inventory. Deterministic
rules handle clear constraints such as location or authorization. Bounded model
judgment may assess career fit, but positive findings must cite canonical facts
that were supplied for the relevant criterion.

Screening helps prioritize jobs; it does not change career facts or remove jobs
from the underlying inventory. When the user applies, the system preserves the
submitted job, resume, and available match information. Later outcomes are
added as new events rather than rewriting history.

### Interfaces and integrations

The command-line interface, web portal, assistant, and scheduled workers call
the same underlying workflows. The portal does not independently decide which
resume is best or whether a candidate is qualified; it displays decisions made
and validated by the backend.

Gmail, Telegram, job providers, and model providers are external adapters.
Their data passes through the same validation boundaries as equivalent manual
input. Credentials and temporary provider state live outside both Git
repositories.

## Where information lives

The system separates reusable code from private career data and disposable
runtime output.

| Area | What it contains | Authority |
|---|---|---|
| Engine repository | Application code, schemas, templates, documentation, and fictional fixtures | Defines system behavior |
| Private workspace | Source snapshots, canonical facts, directions, targets, resumes, and application history | Owns the user's durable career data |
| Runtime storage | Databases, provider caches, credentials, locks, and worker state | Supports execution but is not career truth |
| `build/` | Compiled payloads, reviews, previews, and diagnostic output | Disposable and rebuildable |
| `exports/` | Employer-ready files released by the mint workflow | Output derived from an approved preview |

Important private-workspace sources are:

| Concern | Source of truth |
|---|---|
| Imported evidence | Registered source snapshots |
| Candidate claims | `vault/facts/` |
| Employment organization | `vault/employment/` |
| Reusable role directions | `directions/` |
| Real job postings | `targets/` |
| Editable resumes | `resumes/` |
| Application history | Append-only application records and pinned snapshots |

## Main data flows

Resume creation follows one direction:

```text
imported evidence
    → reviewed career facts
    → role direction or job target
    → synthesis plan
    → editable resume Markdown
    → compiled and reviewed resume
    → web preview
    → released PDF
```

Job and application work follows a separate flow that reads the same facts:

```text
public job posting
    → normalized inventory
    → deterministic eligibility checks
    → evidence-backed fit assessment
    → user decision
    → append-only application record
```

Neither flow may write career facts except through the reviewed vault
change-plan workflow.

## Trust boundaries

The system treats imported documents, job postings, external messages, and
model responses as untrusted input. Each may inform a decision, but only within
a defined boundary.

| Input or component | Allowed to do | Not allowed to do |
|---|---|---|
| Imported resume or career note | Propose candidate facts | Become accepted truth without review |
| Role research | Describe a role and its terminology | Claim that the candidate has that experience |
| Job posting | Define requirements for one opportunity | Add qualifications to the candidate's history |
| Application answer | Preserve and retrieve submitted wording | Create new career facts |
| Application outcome | Help evaluate earlier decisions | Predict hiring probability or silently change scoring rules |
| Language model | Draft prose and make bounded judgments | Invent evidence, grant approval, or increase authorship |
| Compiler | Check citations, structure, and freshness | Judge whether the resume is persuasive or factually true |
| Independent reviewer | Judge selection, language, and hiring position | Create facts or approve unsupported claims |
| Portal, CLI, or worker | Coordinate validated workflows | Become a separate source of business rules or truth |
| Generated cache | Avoid repeated work and reconstruct results | Replace the career workspace or canonical job inventory |

Public job interpretation is kept separate from candidate-private fit analysis.
Any positive fit judgment must cite candidate evidence that was explicitly
retrieved for the requirement being judged.

## Code organization

The Python package is grouped by workflow. Lower-level parsers, schemas, and
validation are kept independent of the commands and interfaces that call them.

| Workflow | Packages |
|---|---|
| Manage evidence and workspace | `vault`, `workspace_management` |
| Define role directions | `role_profiles` |
| Plan and compile resumes | `planning`, `resume_documents`, `construction` |
| Review and release resumes | `reviews`, `quality_assurance`, `publishing`, `build_artifacts`, `document_export` |
| Discover and evaluate jobs | `opportunities`, `matching` |
| Preserve application history | `application_tracking` |
| Provide interfaces and integrations | `portal`, `assistant`, `scheduled_tasks`, `gmail_integration`, `project_status` |

Higher-level workflows call these domains through their public interfaces. The
architecture check rejects package cycles and forbidden reverse imports. In
particular:

- interfaces cannot write canonical facts directly;
- targeting data cannot become candidate evidence;
- compilation depends on canonical inputs, not on the portal or CLI;
- reviewers may judge existing material but cannot create facts; and
- generated artifacts and caches may always be discarded and rebuilt.

## Deployment boundary

The published appliance exposes one portal port. A small process supervisor
runs the portal and optional job, Gmail, and Telegram workers in the same
container while keeping their failures isolated. They share the mounted private
workspace and an external runtime directory, not a new application database of
career truth.

The portal remains available when an optional worker fails. Disabled automation
is a healthy state; enabled but unavailable automation is degraded. The portal
may communicate with its container-private supervisor but receives no Docker or
host-control privileges.

## Guarantees the system must preserve

### Career evidence

- Canonical facts change only through validated change plans.
- Every fact keeps a link to registered source evidence.
- A fact marked `needs-review` cannot appear in visible resume prose.
- Resume wording cannot claim more authorship or authority than the evidence.
- Job postings, research, model output, and application text cannot become
  career facts.

### Resume review and release

- Changing a resume, cited fact, plan, template, or applicable feedback makes
  dependent builds, reviews, and previews out of date.
- Every new or changed narrative block requires a current independent language
  review before preview.
- Additional selection and career review is required only when the review route
  calls for it.
- Minting approves only the exact preview current at the time of the request.
- A PDF cannot be released if it exceeds its page budget, renders incorrectly,
  depends on network content or active JavaScript, or fails text extraction.

### Jobs and applications

- A model cannot override a confirmed eligibility conflict.
- Positive screening findings must cite supplied canonical evidence.
- Screening results and recommendations never replace the job inventory.
- Application events are added rather than rewritten; corrections supersede
  earlier events.
- Submitted resumes and answers are preserved with content fingerprints so the
  exact submitted artifacts can be recovered later.

## Detailed documentation

| Topic | Guide |
|---|---|
| Reasons behind architectural choices | [Design decisions](design-decisions.md) |
| Agent and model behavior | [Agent architecture](agent.md) |
| Portal assistant | [Portal assistant](portal-assistant.md) |
| Job collection | [Job puller](job-puller/README.md) |
| Inventory and duplicate handling | [Job inventory integration](job-inventory-integration.md) |
| Gmail integration | [Gmail automation](gmail-automation.md) |
| Scheduling and workers | [Automation](automation.md) |
| Container operation | [Container deployment](container-deployment.md) |
| Resume regression checks | [Evaluations](evaluations.md) |
