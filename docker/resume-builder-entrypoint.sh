#!/bin/sh
set -eu

workspace="${RESUME_BUILDER_WORKSPACE:-/workspace}"

if [ "$#" -gt 0 ]; then
    if [ "$1" != "serve" ]; then
        exec resume-builder "$@"
    fi
    shift
fi

if [ ! -f "${workspace}/.resume-builder.json" ] && [ ! -f "${workspace}/vault/vault.json" ]; then
    workspace_parent=$(dirname "${workspace}")
    if [ ! -w "${workspace_parent}" ]; then
        workspace="${workspace%/}/workspace"
        export RESUME_BUILDER_WORKSPACE="${workspace}"
    fi
    mkdir -p "${workspace}"
    resume-builder init \
        --workspace "${workspace}" \
        --storage local \
        --git-name "Resume Builder" \
        --git-email "resume-builder@localhost"
fi

cd "${workspace}"

if [ ! -f "automation/config.yml" ]; then
    resume-builder automation init \
        --timezone "${TZ:-America/New_York}" \
        --disabled
fi

exec resume-builder serve \
    --workspace "${workspace}" \
    --host "${RESUME_BUILDER_WEB_HOST:-0.0.0.0}" \
    --port "${RESUME_BUILDER_WEB_PORT:-8765}" \
    --static-dir "${RESUME_BUILDER_WEB_STATIC_DIR:-/app/web/dist}" \
    "$@"
