"""Compatibility facade for the local process supervisor."""

from __future__ import annotations

import sys

from .scheduled_tasks.supervisor import (
    SUPERVISOR_CONFIG_ENV,
    _module_main,
    main,
    managed_service_status,
    render_supervisor_config,
    set_scheduler_enabled,
    telegram_configuration_status,
)

__all__ = [
    "SUPERVISOR_CONFIG_ENV",
    "main",
    "managed_service_status",
    "render_supervisor_config",
    "set_scheduler_enabled",
    "telegram_configuration_status",
]

if __name__ == "__main__":
    raise SystemExit(_module_main(sys.argv[1:]))
