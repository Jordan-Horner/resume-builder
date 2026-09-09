# Container deployment and updates

The published image is a single-container appliance for AMD64 and ARM64. It
runs the portal, scheduler, and optional Telegram worker against the same
workspace and runtime state. CI publishes images only from passing `main`
builds; pull requests never publish them.

## Image channels

- `main`: latest passing build from `main`.
- `sha-<full commit SHA>`: a rebuildable, commit-specific version.
- `@sha256:<digest>`: an exact immutable image; use this for reliable rollback.

Rebuilding a commit can change dependencies, so preserve the image digest—not
just its SHA tag—before an update.

## First deployment

The image is private unless its GHCR package visibility is changed. Authenticate
each Docker host with a credential that can read the package, such as a classic
PAT with `read:packages`. Keep credentials out of Compose and source control.

From a checkout containing `compose.deploy.yaml`:

```sh
docker login ghcr.io
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up -d --no-build --wait --wait-timeout 120
```

Open http://127.0.0.1:8766. The first start creates private workspace and state
volumes. Automatic scraping starts disabled; enable it in **Settings →
Scrapers**. Manual **Find jobs now** runs and the separately managed Gmail
worker do not depend on that switch.

For a trusted private network, set `RESUME_BUILDER_WEB_BIND=0.0.0.0`. The portal
has no authentication boundary, so do not expose it directly to the public
internet. Configure host ports, bind-mounted paths, TLS, and reverse proxies on
the host. The container needs neither privileged mode nor the Docker socket.

## Update checks

**Settings → About** shows the installed revision, release link, last successful
check, and update status. The open portal polls every five minutes; the server
contacts GitHub at most hourly and retries failures after five minutes. It sends
no workspace data. Local builds do not check for updates, and the application
does not install images or restart containers.

The bounded server-side checker lives in `resume_builder.portal.updates`;
`resume_builder.updates` remains its compatibility import.

Private repositories require a separate read-only GitHub credential with
repository Contents access. Save it outside the repository in a file readable
by container UID 1000, restrict its permissions, and set
`RESUME_BUILDER_UPDATE_TOKEN_PATH` to its absolute path. Use both Compose files
for every start, pull, and update:

```sh
docker compose -f compose.deploy.yaml -f compose.updates-private.yaml pull
docker compose -f compose.deploy.yaml -f compose.updates-private.yaml up -d --no-build --wait --wait-timeout 120
```

Public repositories do not need this override. Do not reuse a workflow token
that can write releases.

## Install or roll back an update

Before updating, finish active writes, record the current image digest, keep the
old image locally, and back up the entire persistent workspace and state.
Protect that backup because runtime state may contain credentials. Then:

```sh
docker compose -f compose.deploy.yaml pull
docker compose -f compose.deploy.yaml up -d --no-build --wait --wait-timeout 120
docker compose -f compose.deploy.yaml ps
```

Include `compose.updates-private.yaml` in each command when using private update
checks. A failed health check does not roll back automatically; inspect the host
logs before resuming work.

To use an earlier build, set
`RESUME_BUILDER_IMAGE_TAG=sha-<full commit SHA>` and repeat the commands. For an
exact rollback, override the image with:

```yaml
image: ghcr.io/jordan-horner/resume-builder@sha256:<saved digest>
```

If an update changed stored data incompatibly, stop it and restore the matching
backup before starting the old image. Never use `down -v` to update. Image pulls
also cannot update Compose files; review release notes for host-configuration
changes.

## Release behavior

CI builds and smoke-tests native AMD64 and ARM64 candidates, preserves SBOM and
provenance attestations, then advances `main` and `sha-<commit>` only when both
architectures pass and the commit is still current. Untagged failed candidates
may remain in GHCR. Publishing the image and updating its GitHub prerelease are
separate operations, so rerun a partially failed workflow after fixing its
cause.
