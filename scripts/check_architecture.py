#!/usr/bin/env python3
"""Check orchestration dependency direction and facade budgets."""

from pathlib import Path

from resume_builder.architecture import audit_architecture


def main() -> int:
    package = Path(__file__).resolve().parents[1] / "src" / "resume_builder"
    errors = audit_architecture(package)
    if errors:
        for error in errors:
            print(error)
        return 1
    print("Architecture boundaries valid")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
