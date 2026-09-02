FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    RESUME_BUILDER_WORKSPACE=/workspace \
    RESUME_BUILDER_AUTOMATION_STATE=/state/automation-state.sqlite \
    RESUME_BUILDER_GMAIL_STATE=/state/gmail-state.sqlite \
    RESUME_BUILDER_LOG_LEVEL=INFO \
    RESUME_BUILDER_LOG_FORMAT=text

WORKDIR /app

RUN groupadd --gid 1000 resume-builder \
    && useradd --uid 1000 --gid resume-builder --create-home resume-builder

COPY pyproject.toml README.md LICENSE ./
COPY src ./src
RUN python -m pip install --no-cache-dir ".[gmail]"

RUN mkdir -p /workspace /state \
    && chown -R resume-builder:resume-builder /workspace /state

USER resume-builder
WORKDIR /workspace

HEALTHCHECK --interval=5m --timeout=15s --start-period=2m --retries=3 \
    CMD ["resume-builder", "automation", "status", "--healthcheck"]

ENTRYPOINT ["resume-builder"]
CMD ["automation", "run"]
