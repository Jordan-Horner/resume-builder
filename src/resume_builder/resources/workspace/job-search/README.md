# Job Search

This private directory holds job-discovery preferences, setup state, search
configuration, inventory, and review queues. Fresh workspaces start with an
inactive search configuration and neutral preferences. Resume building does not
require job discovery to be activated.

Use `resume-builder onboard` to continue the optional setup. Saving setup creates
an inactive discovery portfolio under the ignored `build/job-search/` directory.
Activation is a separate operation and never starts a scan immediately.
Active workspaces created before portal onboarding are adopted into setup state
when their search preferences are next saved; provider settings and custom search
families are preserved.
