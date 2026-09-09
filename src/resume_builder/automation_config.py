"""Compatibility facade for scheduled-task configuration."""

from .scheduled_tasks.config import (
    DEFAULT_CONFIG,
    DEFAULT_GMAIL_INTERVAL_HOURS,
    DEFAULT_JOB_TIMES,
    AutomationConfig,
    GmailSchedule,
    JobSchedule,
    NotificationConfig,
    config_payload,
    configure,
    load_config,
    render_default_config,
)

__all__ = [
    "DEFAULT_CONFIG",
    "DEFAULT_GMAIL_INTERVAL_HOURS",
    "DEFAULT_JOB_TIMES",
    "AutomationConfig",
    "GmailSchedule",
    "JobSchedule",
    "NotificationConfig",
    "config_payload",
    "configure",
    "load_config",
    "render_default_config",
]
