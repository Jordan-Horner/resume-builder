# Frontend Design Plan

**Status:** Implemented in the first local release
**Direction:** Calm, simple, and trustworthy

Review safeguards: US country scope preserves listings with unresolved country
information (including bare city names), while explicit foreign country evidence
is excluded. Local city/state filters still narrow non-remote results. OpenRouter
status uses the same saved-key/configured-environment lookup as onboarding;
configured means a credential exists, not that a live provider check succeeded.
Development dependencies include the web-route test dependencies so these tests
execute in CI rather than silently skipping.

## Product shape

The frontend has three pages:

1. **Jobs** — search, filter, and disposition inventory jobs.
2. **Applications** — see the jobs the user applied for and their current status.
3. **Settings** — integration setup/job sources and blocked-company management,
   organized into `/settings/scrapers`, `/settings/integrations`, and
   `/settings/blocked-companies`. Desktop uses left navigation; mobile uses a
   section selector. `/settings` restores the last section (Scrapers initially).
   Existing `/integrations` links resolve to `/settings/integrations`.
   Integration controls and API behavior are unchanged. Editable Job preferences
   are a separate follow-up; no placeholder is shown.

Company blocking lives beside the company name in job details. Blocking hides
matching companies from the review queue, but keeps the current posting open
and changes the button to **Unblock company**. After leaving that posting,
unblocking is available in Settings. Blocks persist in `excluded_companies` in
the workspace preferences; case and punctuation are normalized, without fuzzy
company-name matching. Blocking does not delete inventory or application history.

The first release does not need analytics, a command palette, a separate health
dashboard, advanced workflow management, or a large settings area.

## First-run onboarding

The portal owns the guided first-run experience that previously required CLI or
agent conversation. It collects the minimum information needed for a useful job
search, one decision at a time:

1. Resume, followed by an optional OpenRouter connection for semantic role suggestions.
2. Target roles, using semantic suggestions or manual entry.
3. Search country, location and work mode.
4. Compensation.
5. Review before activation.

The implemented flow begins with resume intake. A fresh workspace opens directly
to a focused upload screen with drag-and-drop and file-picker support for PDF,
DOCX, Markdown, HTML, and text resumes up to 10 MB. Successful uploads are
registered through the canonical source-import workflow; the temporary raw
upload is removed after registration. Reloading the portal returns to a saved
role-suggestion choice instead of asking for the same resume again. `Set up
later` remains available and persists that choice.

OpenRouter is optional. When chosen, it creates evidence-checked adjacent and
exploratory role suggestions; when skipped, the user can keep literal roles
found in the resume and add titles manually. OpenRouter does not change scraper
behavior. Uploads use the existing source-import reader and its Markdown snapshots.
The AI path interprets employment blocks through the shared discovery-evidence
module regardless of heading style or date placement, verifies literal excerpts
against that snapshot, then uses the existing title-generation and portfolio checks.
The CLI reuses this interpretation for layouts its local parser cannot read.
Interpretation neither rewrites the imported source nor creates canonical career facts.
The model selects numbered source lines; the shared reader extracts the actual
excerpt itself rather than relying on a model to reproduce long passages.
The portal caches successful interpretations by resume content and model, so
unchanged retries reuse verified evidence. If an excerpt fails validation, the reader makes
one corrective attempt with validation feedback. A second mismatch still fails
safely; it never accepts invented evidence. The connected OpenRouter button
shows generation progress during this request.
Job providers remain outside onboarding. The remaining steps collect eligibility,
work modes and locations, and optional compensation in compact forms. The final
review offers an Edit action for every section, saves the canonical job preferences,
and activates the generated search families. It does not start a scrape or enable
the scheduler. Older `ready_to_activate` workspaces receive a one-click Finish setup
recovery step instead of being incorrectly treated as complete.

Roles are one wrapping list of removable bubbles: every visible title is included
in search. Add or Enter inserts a role; × removes it with Undo. Duplicate titles
are highlighted instead of repeated. Draft titles and pending input save in this
browser by setup session, with visible recovery errors. Continue submits all visible
roles as search roles and adds pending input before advancing. At least one and
at most 22 roles are supported. There are no Search/Explore or interest categories.
The portal no longer asks authorization, sponsorship, or clearance questions:
these screening inputs are not applied by the Jobs list filters. Search country
lives on Location & work mode and controls the collector location. Existing saved
eligibility answers remain intact; the CLI eligibility workflow remains supported.
Older portal sessions paused at eligibility display the combined location page.

## Navigation

### Inventory filter defaults

Current country-scope behavior (v5): the Jobs API always applies the saved onboarding
country to the combined inventory, regardless of provider or client filter values.
Clear resets viewing filters, not country scope. The page shows the country as a
small scope label, and the location input is optional state/city/region narrowing
for on-site/hybrid jobs. State names match city/state codes. Remote-only jobs skip
local narrowing but still obey country scope. Unspecified locations remain visible.
This does not change provider collection or delete inventory; CLI inventory remains
complete. Browser v5 migration moves saved v4 city input to local narrowing and
uses the workspace country as authority.

Jobs reads `/api/job-filter-defaults` after onboarding and initializes multiple
work modes, country, and minimum compensation. Roles remain discovery inputs,
not inventory filters. A keyword field and a visible location field occupy the
first row. Location starts with the onboarding country and is editable to a city,
region, or country. The second row contains work mode, date, type, salary, and Clear.
Work-mode and salary labels show actual selections. Menus dismiss outside or with Escape.
`/api/jobs` accepts a validated `view_filters` JSON query in addition to legacy
search/date parameters; filtering precedes counting and pagination. These are
read-only viewing settings and never rewrite collection preferences.

Browser state uses `resume-builder.job-view.v4`, migrates the old single-choice
filters, and retains a defaults snapshot. On returning to Jobs, fields that still
follow the old defaults follow updated preferences; custom fields remain intact.
Reset restores current preferences; Clear broadens inventory without bypassing
company blocks or application/dismissal exclusions. Corrupt or unavailable browser
storage surfaces a recovery message.

The v3 simplification restores one compact row: search, visible All/Remote/Hybrid/
On-site buttons, date, job type, and More. Selected work modes remain visible and
support multiple selections. More contains optional location/minimum pay and
reset/clear actions. Role dropdowns, role chips, add-role controls, and the separate
chip row were removed following user feedback. Migration clears v2 role and
automatic location gates while retaining search, dates, work modes, job types,
and compensation choices. Legacy API role values are accepted but ignored.

The v4 migration restores onboarding country where the v3 view had no location,
while keeping custom work-mode, date, keyword, type, and pay selections. Subsequent
location changes (including clearing it) persist. Location matching reuses country
aliases and explicit whole-token terms;
cities constrain non-remote jobs, not remote jobs. Location matching does not infer
country from a bare city or eligibility from the word Remote. US searches also
recognize city/comma/state-code context (Boston, MA), respecting structured country
when supplied. Unspecified/Remote-only locations remain visible as uncertain,
not as confirmed US matches. Scraper behavior is unchanged.
Minimum pay uses the listed upper bound, with a lower-bound fallback when no upper
bound exists. Missing or non-comparable currency/period values are included by
default, controlled by a checkbox; no currency or working-hours conversion is
invented. Target compensation is not a ceiling and does not become a filter.

Integrations includes Job sources with one persisted On/Off toggle per supported
provider. Toggles modify only provider selection (all sources off also leaves the
collector inactive); they never delete inventory or start collection. Company-board
sources show the number of configured boards, including zero when no catalog exists.
Find jobs now runs the existing jobs-new CLI in a separate worker using an enabled
one-off configuration snapshot. Saved discovery portfolios are rendered through
the existing activation preview; the canonical config and scheduling remain unchanged
by a manual scan. A process-held lock prevents duplicate portal scans, and the
existing jobs-new lock coordinates with CLI scans. Durable status reports completion,
partial failures, and new-job counts across navigation and refresh. Interrupted workers
are surfaced as failures. Provider switches are locked during a portal scan.

Endpoints: GET /api/job-sources, PUT /api/job-sources/{provider} with a boolean
enabled value, and POST /api/job-sources/scan. No credentials form is added.

Settings includes Search preferences as the primary editable source of scraper
intent after onboarding. Titles are one removable bubble list; every visible title
becomes a managed search family. Country, work modes, hybrid/on-site locations,
remote location terms, and compensation can be edited without AI or network calls.
Saving preserves provider toggles and manual search families, updates only managed
families, and does not start a scan. Target compensation remains a ranking preference,
not a ceiling. A revision token prevents one open browser tab from overwriting newer
changes from another.

When Jobs has no reviewable inventory, its empty state offers Find jobs now and
polls the existing manual scan status through completion. When jobs exist but filters
hide them, the empty state offers filter recovery instead. A legacy unactivated setup
offers Finish setup before any scrape action.

Use a simple top navigation:

```text
Resume Builder       Jobs     Applications     Integrations
```

The active page is clearly marked. A small status indicator on Integrations may
show when a configured connection needs attention, but global health does not
need its own page.

## Jobs

This is the default page. It shows jobs that have not been dispositioned yet.

### Layout

- One prominent search field.
- One compact work-mode filter.
- A full-width job list.
- Selecting a job opens its details without losing the current search or
  filters. Search and filter choices persist in the browser across navigation,
  reloads, and returning to the app later.

### Filters

Use one segmented filter with four choices:

```text
All jobs       Remote     Hybrid     On-site
```

Search applies only to jobs awaiting a decision and matches job title, company,
location, and description. Show `X jobs to review` so the user knows when the work-mode
filter or search is narrowing the inbox.

Opening a job is read-only. It stays in the review queue until the user chooses
`Not interested` or `Applied`. The first action dismisses it; the second creates
an application record and moves it to Applications. Store disposition state in
the backend so it is consistent across browser sessions.

Following CareerPulse's job-detail pattern, keep the disposition and posting
actions in a persistent action area beside the content. In the split pane, the
job summary and actions remain fixed while only the long description scrolls.
On desktop, treat the Jobs screen as a fixed-height workspace like LinkedIn:
the page heading and filters stay in place, the inventory list scrolls in its
own frame, and the detail description scrolls independently in the adjacent
frame. Do not apply this split-frame behavior to the mobile single-pane view.
Use compact application-scale typography and controls rather than landing-page
scale: keep the page title on the same line as its supporting copy, fit the
three job actions on one row when the pane permits, and prioritize visible job
rows and description reading space.
Favor the reading pane in the desktop split: allocate roughly 36% to the job
list and 64% to job detail. Keep inventory rows compact, while rendering the
description at a larger reading size with a comfortable line height and bounded
line length.

### Job row

Each row shows:

- Job title.
- Company.
- Location and work mode.
- Salary when available.
- Date posted or first seen.
- Source/provider.
- A small `New` label.

The row should be easy to scan. Do not turn every job into a large card.

### Job detail

Show the selected job in a simple side panel on desktop and a full page on
mobile:

- Title, company, location, work mode, and salary.
- Full job description.
- Original posting link.
- Source and freshness information.
- `Open posting`, `Mark as applied`, and `Not interested`, in that review order.

Marking a job as applied removes it from the review queue and moves it to Applications.

## Applications

Use a straightforward list grouped or filtered by status.

### Statuses

- Applied.
- Interviewing.
- Offer.
- Rejected.
- Withdrawn.

### Application row

Each row shows:

- Job title and company.
- Current status.
- Date applied.
- Most recent update.
- Link back to the inventory job when available.

The user can filter by status and search by title or company. Selecting an
application shows its status history in chronological order. This stays a list,
not a drag-and-drop board.

## Integrations

Show one simple row for each supported integration:

- Gmail — application-status tracking.
- Telegram — private conversations with the agent.
- Discord — notifications.
- OpenRouter — AI screening.
- Job providers — LinkedIn, Indeed, and configured ATS boards.

Each row shows:

- What the integration does.
- Connected, not connected, or needs attention.
- One action: `Set up`, `Manage`, or `Fix`.

Selecting an integration opens a short setup flow on the same page. The flow
explains what data is shared, asks only for required information, verifies the
connection, and ends with a clear success state. Secrets are sent only to the
local backend and are never shown again after saving.

## CareerPulse inspiration

Borrow these patterns from the local CareerPulse project:

- Clear top navigation between jobs, applications, and setup.
- A search-first job feed with work type visible beside search.
- Obvious `New` treatment and readable job metadata.
- A separate home for applied jobs and their statuses.
- Integration forms that verify a connection after it is configured.

Do not carry over CareerPulse's score filters, saved views, alerts, batch tools,
analytics dashboard, queue, networking area, dense settings tabs, or kanban
pipeline. The Resume Builder frontend has a smaller job: review inventory jobs,
check applications, and connect services.

## Visual direction

- Base the interface on GitHub Dark Default: neutral blue-charcoal backgrounds,
  subtly lighter elevated surfaces, soft cool-white text, and blue accents.
- Use blue for navigation and selection, green for positive actions, amber for
  attention, and red only for destructive or failed states.
- Avoid pure black, stark white, glowing accents, and shadow-heavy depth.
- One readable sans-serif font family.
- Fine dividers and spacing instead of card-heavy layouts and shadows.
- Status always uses text as well as color.
- Restrained motion only for opening details and showing setup progress.

## Responsive behavior

- Desktop: full-width lists with a job or application detail panel.
- Tablet: lists remain full width; details replace the list when opened.
- Mobile: the work-mode options remain a compact horizontal control and job
  details use a separate screen with a clear back action.

Search, filters, application status, and integration setup remain fully usable
with keyboard navigation and at 200% zoom.

## Technical shape

- React, Vite, and TypeScript in a `web/` directory.
- A small Python API that calls existing Resume Builder services.
- URL parameters preserve job search and filters.
- The Python backend remains the source of truth for jobs, applications, and
  integration state.

The onboarding and dashboard API includes:

- `GET /api/onboarding`
- `POST /api/onboarding/resume`
- `POST /api/onboarding/skip`
- `POST /api/onboarding/start`
- `POST /api/onboarding/answer`
- `POST /api/onboarding/back`
- `POST /api/job-search/activate`
- `GET /api/job-search/preferences`
- `PUT /api/job-search/preferences`
- `GET /api/jobs?search=&work_mode=&date_days=&employment_type=`
- `GET /api/jobs/{job_id}`
- `POST /api/jobs/{job_id}/not-interested`
- `POST /api/jobs/{job_id}/applied`
- `GET /api/applications`
- `GET /api/applications/{application_id}`
- `GET /api/integrations`
- Setup and verification actions for each supported integration.

## Build order

1. Add persistent resume intake to the first-run portal. **Complete.**
2. Offer optional semantic role suggestions without making AI mandatory. **Complete.**
3. Move role, eligibility, work-mode, location, and compensation setup into the portal. **Complete.**
4. Add a review screen that activates confirmed search families without starting a scrape. **Complete.**
5. Continue browser-level accessibility and failure-state testing before a public release.

## First-release success

- The main page contains only jobs that have not been dismissed or applied to.
- The user can search reviewable jobs and filter them by Remote, Hybrid, or On-site.
- Opening a job never removes it; only `Not interested` or `Applied` moves it
  out of the review queue.
- The user can see all applications and their current statuses.
- The user can set up or repair an integration without using the CLI.
