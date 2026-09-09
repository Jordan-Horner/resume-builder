"""Compatibility facade for career-vault schema upgrades."""

from .vault.schema_upgrade import (
    SchemaUpgradePlan,
    apply_upgrade_plan,
    build_upgrade_plan,
    create_backup,
    insert_scope,
    load_role_map,
    main,
    read_v1_config,
    validate_staged_upgrade,
    validate_vault,
)

__all__ = [
    "SchemaUpgradePlan",
    "apply_upgrade_plan",
    "build_upgrade_plan",
    "create_backup",
    "insert_scope",
    "load_role_map",
    "main",
    "read_v1_config",
    "validate_staged_upgrade",
    "validate_vault",
]
