# Resume Builder

**Keep the strongest parts of every resume version, then build honest, targeted
resumes without starting over.**

Your career is bigger than two pages. What matters most will change with each
opportunity, so tailor every resume to the job while preserving the rest of your
story.

Resume Builder gives an AI agent a private, organized record of your career. It
brings together useful details scattered across old resumes, LinkedIn exports,
and career notes so they remain available for future resumes.

**Requires:** a local source checkout · Python 3.10 or newer · Codex or Claude Code

## Start here

Clone this repository, open the checkout in Codex or Claude Code, and say:

```text
Set up Resume Builder and help me import my existing resume.
```

The agent installs the project, starts the introduction, creates your private
workspace, and asks how you want to protect it. Returning users skip first-run
intake because the agent inspects the existing workspace before asking questions.

Once setup is complete, you can ask naturally:

```text
Build a Support Operations resume from my career history.
Screen this job: <posting URL>
Tailor my closest resume to this job description: <paste description>
Update my Incident Management resume without losing approved content.
What important experience is missing from this draft?
```

Quick screens and detailed matches use the same gate-first semantic classifier.
It keeps required role evidence separate from resume polish and exact keyword
retrieval, and it never reports an ATS score or interview probability.

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

## See the preservation model in one minute

The included Phoenix Wright fixture starts with one fictional career record. The
agent selects the evidence that supports a senior criminal-defense direction,
keeps adverse history available without presenting it as an accomplishment, and
refuses to use mentorship claims whose exact role placement is unresolved.

[![Phoenix Wright evidence flows from a career vault through targeting decisions into a focused resume](docs/assets/phoenix-demo-flow.svg)](examples/phoenix-wright/README.md)

| Vault evidence | Resume decision | What the safeguard proves |
|---|---|---|
| Reconstructed a fifteen-year-old case | Lead with it | Strong, target-relevant proof is easy to find. |
| Supported another attorney as co-counsel | Include with limited ownership | Collaboration does not become false leadership. |
| Disbarment history | Preserve; do not sell | A true fact does not automatically belong on a resume. |
| Mentorship under an unresolved interim title | Hold for clarification | The agent does not guess chronology to complete a story. |

The [complete fictional case study](examples/phoenix-wright/README.md) shows the
source material, selection decisions, current resume, and an alternate direction
the evidence cannot yet support cleanly.

## Why this exists

Changing a resume for one opportunity can quietly remove a strong bullet, metric,
project, or leadership example that would help with the next one. Repeated AI
rewrites create another risk: wording can become stronger than the underlying
experience.

Resume Builder keeps your career history separate from any individual resume:

- Old accomplishments remain available even when they do not fit the current
  target.
- Each resume can emphasize a different direction without changing the facts.
- Job descriptions guide what to highlight but never become evidence about you.
- New memories strengthen future resumes instead of living in one temporary chat.

There is no single “master resume” that must contain everything. Your private
career record is the foundation; each resume is a focused view of that record.

## What the agent does

1. **Builds your career record.** Import resumes, pasted text, a LinkedIn export,
   career notes, or begin with a guided interview. Useful claims retain their
   sources and employment context.
2. **Targets one direction.** Choose a role or provide a real job posting. The
   agent selects relevant stories and records what it intentionally leaves out.
3. **Drafts and checks the resume.** It looks for unsupported metrics,
   exaggerated authority, lost accomplishments, weak wording, and missing
   evidence. Named content templates keep section architecture explicit, while
   separately selected visual themes control appearance without changing the
   career argument.
4. **Shows you the result.** An independent reviewer always checks new or changed
   resume language. A deeper career-strategist and hiring-manager review runs
   when the resume is competitive but can be positioned more strongly. You
   approve a readable web preview before the system
   creates a final, format-checked PDF. The preview step returns a structured,
   required handoff with organized, ready-to-post Markdown so the agent presents
   the complete review prompt instead of merely generating a file in the
   background. For a real posting, the browser tab, preview handoff, and mint
   result identify the company and role so concurrent applications remain easy
   to distinguish. Final application PDFs are collected under `exports/resumes/`;
   company targeting stays in the folder name, while the upload-visible PDF uses
   the neutral `<candidate-name>-Resume.pdf` filename. Internal manifests,
   previews, and diagnostics stay grouped under
   `build/resumes/<resume-slug>/`.

Resume presentation is extensible without forking the resume workflow. Content
templates control allowed sections and their order; visual themes control only
typography, color, spacing, and print styling. Workspaces include a compatible
default and an alternate conservative theme. Use
`resume-builder workspace templates list` to inspect them,
`resume-builder workspace templates scaffold theme <id>` to create a custom
theme, and `resume-builder workspace templates validate` before using it.

If a draft is weak, the agent checks your saved career evidence and imported
sources before asking a question. It asks only focused questions that could
materially improve the resume; it does not ask you to repeat information it
already has or invent a metric to fill a gap.

## Your career data stays private

The reusable Resume Builder engine and your personal career data use separate Git
repositories inside one project folder:

```text
resume-builder/          Reusable engine
└── workspace/           Your ignored, private Git repository
    ├── vault/           Career sources and facts
    ├── directions/      Roles you may pursue
    ├── targets/         Job postings you choose to save
    └── resumes/         Your resume source files
```

The public engine ignores `workspace/`, so normal engine commits do not include
your career files. During setup, choose either:

1. **Local Git with a private GitHub backup** (recommended).
2. **Local Git only** if you do not want anything uploaded.
3. **An existing private workspace** that you already manage.

Nothing is uploaded without confirmation. A private backup is recommended because
local Git cannot recover files after device loss.

If a repository has ever contained real career data, keep its complete Git history
private. Removing personal files from the latest version does not remove them from
earlier commits.

## How it keeps the result honest

- **Claims retain their sources.** Resume statements can be traced back to saved
  career evidence.
- **Targeting cannot become biography.** A role profile or job posting can guide
  selection but cannot establish candidate experience.
- **Important information is checked for accidental removal.** Plans and
  regression checks distinguish deliberate targeting from a lost accomplishment.
  Every new or changed narrative block receives an independent language check
  before preview. Exact approved unchanged blocks are reused. The deeper career
  review runs only when hybrid routing finds an improvable fit or the user asks
  for it.
- **The user owns the wording loop.** The normal lifecycle is build, language
  review, preview, edit, changed-block review, preview, and mint. An explicit
  mint request approves the current
  preview; mint then performs the hard source, evidence, page, rendering, and
  PDF-extraction checks.
- **Drafting stays conversational until wording is chosen.** If you reject or
  question a sentence, the agent proposes distinct alternatives without
  starting build and review work. Once you select one, only the changed language
  is reviewed; unchanged strategy and hiring judgments carry forward.

These safeguards do not predict an employer's decision or produce a universal ATS
score. They make the resume easier to verify, revise, and defend.

## Help and contributing

For setup problems or feature requests, [open an
issue](https://github.com/Jordan-Horner/resume-builder/issues/new). Use fictional or
redacted examples only—never attach a real resume, career source, contact details,
or private job-search information to a public issue.

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
