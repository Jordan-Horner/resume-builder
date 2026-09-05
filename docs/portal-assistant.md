# Portal assistant

The portal uses CopilotKit's local, runtime-backed transport. It does not require
a CopilotKit account or cloud service. OpenRouter credentials and model choices
remain in the existing server-side integration configuration; model usage is billed
by that provider. Telemetry and CopilotKit channels are disabled.

## Deployment

The appliance remains one container and one public port. Supervisor starts a local
Node runtime on loopback port 8768 alongside FastAPI. FastAPI proxies only known
runtime routes. A random per-start token protects the private Python AG-UI endpoint.
Do not expose port 8768. Development uses the separate container on localhost:8767.
Production is not updated by building the development image.

Conversation history and pending wording proposals live in the existing agent SQLite
state file (`RESUME_BUILDER_AGENT_STATE`, `/state/agent-state.sqlite` in Docker).
Persist `/state` alongside the career workspace. This is a single-user private portal,
not a multi-tenant authentication boundary. Keep it behind your private network or
an authenticated reverse proxy.

## Initial scope

Open Assistant for job-queue questions, or select Discuss resume on a directional
resume. Context is explicit and does not silently follow navigation. History survives
refresh; Stop cancels a response. The UI is lazy-loaded and uses the portal dark theme.
On desktop and tablet it floats at the bottom right (400px wide, up to 620px tall),
without resizing or hiding the workspace. Only phone viewports up to 480px use
a full-screen chat surface. Closing the window preserves the conversation.
Responses currently show working progress followed by the completed answer, not
token-by-token model output.

The assistant can propose one wording-only block replacement. A before/after card
offers Use this wording or Keep current. Accepting claims a durable proposal once,
checks the source revision and factual equivalence, records existing feedback, compiles,
runs an independent language review, and invokes the existing preview pipeline.
The vault, other resumes, and minted application artifacts remain unchanged.
Factual enrichment, minting, deletion and application submission are not exposed as
agent write tools in this initial release. A failure after saving prose explicitly
reports that the current draft needs review; it never pretends to roll it back.

Restarted operations are marked interrupted, not automatically replayed. A repeated
acceptance cannot apply the same proposal twice. New proposals against stale source
revisions must be regenerated. Exploration itself does not record editorial memory.

## Verification

Run the Python suite, frontend tests/typecheck/build, and `npm test` from
`assistant-runtime`. Runtime tests cover production-mode discovery and AG-UI forwarding
without vendor credentials. Backend tests cover durable state, isolated proposals,
stale revisions, factual-change rejection and reuse of review/preview services.
Live model quality and costs still depend on the self-hoster's configured provider.
