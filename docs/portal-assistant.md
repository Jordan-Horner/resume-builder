# Portal assistant

The portal uses a small same-origin HTTP transport backed directly by FastAPI. It
does not require a CopilotKit account, browser SDK, or cloud service. OpenRouter
credentials and model choices remain in the existing server-side integration
configuration; model usage is billed by that provider.

After onboarding, use **Settings → Integrations → OpenRouter** to add or replace
the API key. Save and connect verifies the key with OpenRouter's
[key endpoint](https://openrouter.ai/docs/api/reference/limits) before using the
existing secret store. It creates default agent configuration only when missing,
preserves existing model choices, and does not restart onboarding or scrape jobs.
Keys are never returned to the browser; a rejected key leaves the old one intact.

## Deployment

The browser talks only to the appliance's existing public port. Assistant runs start
through `/api/assistant/threads/{id}/runs`, while the browser polls the durable thread
record only while the assistant is open. The older loopback runtime bridge remains
available for compatibility with existing deployments, but it is no longer loaded
by the web frontend or required for frontend health.

Conversation history and pending wording proposals live in the existing agent SQLite
state file (`RESUME_BUILDER_AGENT_STATE`, `/state/agent-state.sqlite` in Docker).
Persist `/state` alongside the career workspace. This is a single-user private portal,
not a multi-tenant authentication boundary. Keep it behind your private network or
an authenticated reverse proxy.

## Capabilities

Open Assistant for job-queue questions, select **Discuss job** on a job, or select
**Discuss résumé** on a directional resume. Context is explicit and does not silently
follow navigation. History survives
refresh; Stop cancels a response. The UI is lazy-loaded and uses the portal dark theme.
On desktop and tablet it floats at the bottom right (400px wide, up to 620px tall),
without resizing or hiding the workspace. Only phone viewports up to 480px use
a full-screen chat surface. Closing the window preserves the conversation.
Responses currently show working progress followed by the completed answer, not
token-by-token model output.

The assistant can run the existing bounded, deterministic-plus-semantic job screen for
an explicitly attached job. The same cached result appears in the job detail; screening
does not submit, dismiss, or otherwise change the job. For a new or changed posting,
the service also builds a candidate-independent, source-backed interpretation in a
separate shadow request. This generated interpretation is cached but does not yet
change the visible fit result or select candidate evidence.

The assistant can propose one wording-only block replacement. A before/after card
offers Use this wording or Keep current. Accepting claims a durable proposal once,
checks the source revision and factual equivalence, records existing feedback, compiles,
runs an independent language review, and invokes the existing preview pipeline.
The assistant can also propose removing an attached or uniquely named directional résumé from
the résumé library.
Removal requires a separate confirmation card and archives the Markdown source out of
active matching. When applications reference it, the operation first stores one immutable,
content-addressed copy per unique résumé and then retires the directional source. Application
history can continue rendering the exact recorded copy without duplicating identical files.
Retired résumés remain available in a collapsed library section and can be restored. Vault
evidence, source material, other résumés, and minted tailored application artifacts remain
unchanged. Factual enrichment, minting, permanent deletion,
and application submission are not exposed as agent write tools. A failure after saving prose explicitly
reports that the current draft needs review; it never pretends to roll it back.

Restarted operations are marked interrupted, not automatically replayed. A repeated
acceptance cannot apply the same proposal twice. New proposals against stale source
revisions must be regenerated. Exploration itself does not record editorial memory.

## Verification

Run the Python suite and frontend tests/typecheck/build. The compatibility runtime
has its own tests under `assistant-runtime`. Backend tests cover durable state, isolated proposals,
stale revisions, factual-change rejection and reuse of review/preview services.
Live model quality and costs still depend on the self-hoster's configured provider.
Message-submission tests explicitly cover HTTP LAN origins where `crypto.randomUUID`
is unavailable, and verify that preparation failures preserve input and show an error.
