from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

MANIFEST_PATH = Path("docs/assets/phoenix-demo-assets.json")
INPUTS = (
    Path("scripts/capture_demo_resume.py"),
    Path("examples/phoenix-wright/README.md"),
    Path("examples/phoenix-wright/workspace/directions/senior-defense-attorney.md"),
    Path("examples/phoenix-wright/workspace/resumes/plans/senior-defense-attorney.yaml"),
    Path("examples/phoenix-wright/workspace/resumes/baselines/senior-defense-attorney.md"),
    Path("examples/phoenix-wright/workspace/resumes/selections/senior-defense-attorney.json"),
    Path("examples/phoenix-wright/workspace/templates/resume-template.html"),
)
ASSETS = (
    Path("docs/assets/phoenix-demo-flow.svg"),
    Path("docs/assets/phoenix-wright-resume.jpg"),
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _records(root: Path, paths: tuple[Path, ...]) -> dict[str, str]:
    records: dict[str, str] = {}
    for relative in paths:
        path = root / relative
        if not path.is_file():
            raise ValueError(f"missing demo file: {relative.as_posix()}")
        records[relative.as_posix()] = _sha256(path)
    return records


def current_manifest(root: Path) -> dict[str, object]:
    return {
        "version": 1,
        "inputs": _records(root, INPUTS),
        "assets": _records(root, ASSETS),
    }


def check(root: Path) -> list[str]:
    manifest_path = root / MANIFEST_PATH
    if not manifest_path.is_file():
        return [f"missing demo manifest: {MANIFEST_PATH.as_posix()}"]
    try:
        saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        current = current_manifest(root)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        return [str(exc)]
    if saved == current:
        return []

    errors: list[str] = []
    for section in ("inputs", "assets"):
        saved_records = saved.get(section, {}) if isinstance(saved, dict) else {}
        current_records = current[section]
        if not isinstance(saved_records, dict):
            errors.append(f"demo manifest {section} must be an object")
            continue
        for path, digest in current_records.items():
            if saved_records.get(path) != digest:
                errors.append(f"stale demo {section[:-1]}: {path}")
        for path in saved_records.keys() - current_records.keys():
            errors.append(f"unexpected demo {section[:-1]}: {path}")
    return errors or ["demo manifest metadata is stale"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check that public Phoenix demo assets match their reviewed inputs."
    )
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--update", action="store_true")
    args = parser.parse_args()
    root = args.root.resolve()
    manifest_path = root / MANIFEST_PATH

    if args.update:
        manifest = current_manifest(root)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(
            json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        print(f"Updated {MANIFEST_PATH.as_posix()}")
        return 0

    errors = check(root)
    if errors:
        for error in errors:
            print(error)
        print("Run python3 scripts/check_demo_assets.py --update after reviewing refreshed assets.")
        return 1
    print("Phoenix demo assets are current.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
