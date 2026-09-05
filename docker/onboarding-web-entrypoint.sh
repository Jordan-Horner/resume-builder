#!/bin/sh
set -eu

workspace="${RESUME_BUILDER_WORKSPACE:-/onboarding/workspace}"

if [ ! -f "${workspace}/.resume-builder.json" ]; then
    mkdir -p "${workspace}"
    resume-builder init \
        --workspace "${workspace}" \
        --storage local \
        --git-name "Resume Builder" \
        --git-email "resume-builder@localhost"
fi

exec resume-builder-web \
    --workspace "${workspace}" \
    --host 0.0.0.0 \
    --port "${RESUME_BUILDER_WEB_PORT:-8765}" \
    --static-dir /app/web/dist
