FROM node:22-alpine AS web-build

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESUME_BUILDER_WORKSPACE=/workspace \
    RESUME_BUILDER_AUTOMATION_STATE=/state/automation-state.sqlite \
    RESUME_BUILDER_GMAIL_STATE=/state/gmail-state.sqlite \
    RESUME_BUILDER_LOG_LEVEL=INFO \
    RESUME_BUILDER_LOG_FORMAT=text

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 resume-builder \
    && useradd --uid 1000 --gid resume-builder --create-home resume-builder

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[agent,gmail,telegram,web]"
COPY --from=web-build /web/dist /app/web/dist
COPY docker/onboarding-web-entrypoint.sh /usr/local/bin/onboarding-web-entrypoint
RUN chmod 0755 /usr/local/bin/onboarding-web-entrypoint

RUN mkdir -p /workspace /state /onboarding \
    && chown -R resume-builder:resume-builder /workspace /state /onboarding

USER resume-builder
WORKDIR /workspace

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD ["resume-builder", "automation", "status", "--healthcheck"]

ENTRYPOINT ["resume-builder"]
CMD ["automation", "run"]
