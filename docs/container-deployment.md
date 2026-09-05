# Container releases and host-managed updates

Every push to `main` runs Python, frontend, security, and container checks. Only
after all jobs pass does CI publish an AMD64/ARM64 image to
`ghcr.io/jordan-horner/resume-builder`. Pull requests never publish images.
The local-build Compose file remains a development configuration. The published
image is a single-container appliance: the portal, scheduler, and optional
Telegram worker start together and share the same mounted workspace and runtime
state.

## Channels and identity

- `main`: the most recently published passing build, a rolling development channel.
- `sha-<full commit SHA>`: commit-addressed build for selecting a previous version.
- `@sha256:<digest>`: exact immutable image identity (prefer for archival rollback).

CI serializes publication and skips superseded commits. Image labels and runtime
metadata record the commit, commit date, and channel. After a successful image
push, CI updates a dedicated moving `main-build` tag and prerelease with the image
digest and source link. Do not use that reserved tag for stable releases or enable
release immutability on it. Numbered stable channels are not implemented yet.
Rebuilding a commit can change dependencies; a SHA tag is not a substitute for
an immutable digest. A failed announcement leaves an available image unannounced;
rerun the workflow after resolving the failure.

## First deployment

Keep the image private unless you deliberately change its package visibility in
GitHub. On each Docker host, authenticate using `docker login ghcr.io` with a
credential allowed to read the package (classic PAT with `read:packages` and
access to the package). Do not put credentials in Compose or commit them.

From a checkout containing `compose.deploy.yaml`:

```sh
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up -d --no-build --wait --wait-timeout 120
```

The portal is available at http://127.0.0.1:8766. Fresh deployments use the
`resume-builder-workspace` and `resume-builder-state` volumes. The container
creates a private workspace inside the empty workspace volume and an inactive
scheduler configuration on first start;
automatic scraping is enabled later in **Settings → Scrapers**. No Docker socket
or privileged mode is used.

For a trusted LAN such as a private TrueNAS network, set
`RESUME_BUILDER_WEB_BIND=0.0.0.0`. Do not expose the unauthenticated portal to the
public internet. Host ports, volume paths, image tags, TLS, and reverse-proxy
settings remain host deployment concerns rather than portal settings.

## Migrate an existing two-container installation

1. Record the current image identity and take a restorable snapshot of both the
   private workspace and runtime directory.
2. Stop the existing automation and Telegram containers. Do not start the new
   appliance while either old writer is running.
3. Set `RESUME_BUILDER_WORKSPACE_PATH` and `RESUME_BUILDER_RUNTIME_PATH` to the
   existing host directories. When these are unset, Compose creates fresh named
   volumes instead.
4. Start the new `resume-builder` service and open Settings → About. Confirm the
   Portal and Scheduler rows are online before enabling or changing a schedule.
5. Keep the previous Compose definition and image available for rollback. Image
   rollback does not reverse an incompatible data migration, so restore the
   matching snapshot if stored data ever changes incompatibly.

The scheduler's exclusive lock prevents a duplicate writer, but stopping the old
containers is still a required migration step. A lock conflict is reported as a
degraded Scheduler state rather than silently running twice.

## Update checks in the portal

Settings → About displays installed version, channel, revision, last successful
check, and update status. A compact indicator beside Settings links to About;
on mobile only its amber dot is shown, with an accessible label. About includes
the release link and dismissal control. Dismissal is browser-local and specific to that revision. It does not
hide the status in About or dismiss future builds.

While the portal is open it polls its read-only API every five minutes. The
server checks GitHub at most hourly, retrying failures after five minutes. No
resume, job, or workspace data is sent. Offline or malformed responses are
reported as unavailable, never as up to date. Local builds do not check GitHub.
There is no installation endpoint, background Docker updater, or restart button.

For a private repository, update checks need a **separate read-only GitHub
credential** with repository Contents read access. Host Docker login does not
grant access to GitHub release metadata inside the container. Save that token
outside the repository in a file readable by container UID 1000, restrict its
permissions, and set `RESUME_BUILDER_UPDATE_TOKEN_PATH` to its absolute path.
Then consistently use both Compose files for start, pull, and update:

```sh
docker compose -f compose.deploy.yaml -f compose.updates-private.yaml up -d --no-build --wait
```

This mounts only that file as a read-only secret. Public repositories do not need
the override. Never reuse the workflow's write-capable token for update checks.

## Install an update and recover

1. Record the current container's image ID/digest and keep the old image locally.
2. Finish active operations, stop the container that writes to the workspace, and
   take a restorable snapshot/backup of the **entire** persistent volume. Keep
   credentials protected in backups. Use your host's volume backup tooling.
3. Pull the image, then recreate and verify health:

```sh
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up -d --no-build --wait --wait-timeout 120
docker compose -f compose.deploy.yaml ps
```

Include the private-check override above if used. An unsuccessful health check
returns a failure; Compose does not automatically roll back. Inspect logs on the
host before resuming work. Settings → About should show the new build afterward.

To select a previous commit, set `RESUME_BUILDER_IMAGE_TAG=sha-<full SHA>` and run
the same pull/up commands. For exact digest pinning, use a local Compose override
with `image: ghcr.io/jordan-horner/resume-builder@sha256:<saved digest>`.
If an update migrated stored data incompatibly, stop it and restore the matching
backup before running the old image. Never assume an image rollback reverses
data migrations. Do not use `down -v` or delete the workspace volume to update.

Compose file changes are separate from image updates: review and obtain updated
deployment files when release notes require them. Pulling an image cannot change
host configuration. Docker-host tools may monitor the `main` tag independently;
automatic installation is not enabled by this project.
