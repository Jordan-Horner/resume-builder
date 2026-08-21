from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from resume_builder import selection_guard, synthesis

FIXTURE_ROOT = Path(__file__).parents[1] / "examples" / "phoenix-wright"
SOURCE_ID = re.compile(r"SRC-[0-9a-f]{12}")


def _run(workspace: Path, *arguments: str) -> subprocess.CompletedProcess[str]:
    environment = os.environ.copy()
    environment["RESUME_BUILDER_WORKSPACE"] = str(workspace)
    return subprocess.run(
        [sys.executable, "-m", "resume_builder", *arguments],
        cwd=workspace,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )


def _copy_clean_fixture(workspace: Path) -> None:
    """Copy only canonical fixture inputs, never ignored local build artifacts."""
    shutil.copytree(
        FIXTURE_ROOT / "workspace",
        workspace,
        ignore=shutil.ignore_patterns("build"),
    )


def test_phoenix_fixture_validates_compiles_and_prepares_review(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _copy_clean_fixture(workspace)

    validation = _run(workspace, "validate", "--strict")
    assert validation.returncode == 0, validation.stderr or validation.stdout

    direction = _run(workspace, "direction", "validate")
    assert direction.returncode == 0, direction.stderr or direction.stdout

    synthesis = _run(
        workspace,
        "synthesis",
        "resumes/plans/senior-defense-attorney.yaml",
    )
    assert synthesis.returncode == 0, synthesis.stderr or synthesis.stdout

    verification = _run(
        workspace,
        "verify",
        "resumes/baselines/senior-defense-attorney.md",
    )
    assert verification.returncode == 0, verification.stderr or verification.stdout
    verification_result = json.loads(verification.stdout)
    assert verification_result["state"]["state"] == "awaiting-selection-review"
    assert (
        workspace / "build" / "resumes" / "senior-defense-attorney" / "resume.verify.json"
    ).is_file()
    assert not (workspace / "build" / "reviews" / "senior-defense-attorney.cold.json").exists()

    decisions_path = (
        workspace / "build" / "reviews" / "senior-defense-attorney.selection.decisions.json"
    )
    decisions = json.loads(decisions_path.read_text(encoding="utf-8"))
    decisions["reviewer"]["context"] = "Independent fixture selection review."
    decisions["argument"] = {"decision": "approved", "note": "Complete argument."}
    for group in ("stories", "exclusions", "role_arcs"):
        for item in decisions[group]:
            item["decision"] = "approved"
    decisions["verdict"] = "approved"
    decisions_path.write_text(json.dumps(decisions), encoding="utf-8")

    finalized = _run(
        workspace,
        "review",
        "selection-finalize",
        "build/reviews/senior-defense-attorney.selection.decisions.json",
    )
    assert finalized.returncode == 0, finalized.stderr or finalized.stdout

    language_package = _run(
        workspace,
        "review",
        "language-package",
        "resumes/baselines/senior-defense-attorney.md",
    )
    assert language_package.returncode == 0, language_package.stderr or language_package.stdout
    language_decisions_path = (
        workspace / "build" / "reviews" / "senior-defense-attorney.language.decisions.json"
    )
    language_decisions = json.loads(language_decisions_path.read_text(encoding="utf-8"))
    language_decisions["reviewer"]["context"] = (
        "Independent fixture reviewer saw only the frozen language package."
    )
    language_decisions["language_review"]["status"] = "approved"
    for block in language_decisions["language_review"]["blocks"]:
        block["decision"] = "approved"
    language_decisions_path.write_text(json.dumps(language_decisions), encoding="utf-8")
    language_finalized = _run(
        workspace,
        "review",
        "language-finalize",
        "build/reviews/senior-defense-attorney.language.decisions.json",
    )
    assert language_finalized.returncode == 0, (
        language_finalized.stderr or language_finalized.stdout
    )

    language_handoff = _run(
        workspace,
        "verify",
        "resumes/baselines/senior-defense-attorney.md",
    )
    assert language_handoff.returncode == 0, language_handoff.stderr or language_handoff.stdout
    assert (workspace / "build" / "reviews" / "senior-defense-attorney.cold.json").is_file()


def test_phoenix_review_cannot_pass_by_deleting_weak_stories(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    _copy_clean_fixture(workspace)
    verification = _run(
        workspace,
        "verify",
        "resumes/baselines/senior-defense-attorney.md",
    )
    assert verification.returncode == 0, verification.stderr or verification.stdout

    package = json.loads(
        (
            workspace / "build" / "reviews" / "senior-defense-attorney.selection.package.json"
        ).read_text()
    )
    previous = json.loads(json.dumps(package["selection"]))
    plan = synthesis.load_synthesis_plan(
        Path("resumes/plans/senior-defense-attorney.yaml"),
        workspace,
        workspace / "vault",
    )
    current_story_ids = {story["id"] for story in previous["stories"]}
    for story in plan.stories:
        if story.story_id in current_story_ids:
            continue
        previous["stories"].append(
            {
                "id": story.story_id,
                "section": story.section,
                "role_ids": sorted(story.role_ids),
                "importance": story.importance,
                "required": False,
                "used_fact_ids": sorted(story.core_fact_ids),
            }
        )
    previous["progression_role_ids"].append("BBC-001")
    previous["stories"].append(
        {
            "id": "borscht-investigation",
            "section": "experience",
            "role_ids": ["BBC-001"],
            "importance": "supporting",
            "required": False,
            "used_fact_ids": ["BBC-002"],
        }
    )
    previous["role_arcs"].append(
        {
            "role_ids": ["BBC-001"],
            "required_dimensions": ["investigation"],
            "required_story_ids": [],
        }
    )
    previous["progression_role_ids"].sort()
    previous["stories"].sort(key=lambda story: story["id"])
    previous["role_arcs"].sort(key=lambda arc: arc["role_ids"])
    fake_review = workspace / "build" / "reviews" / "prior-approved.json"
    fake_review.write_text("{}", encoding="utf-8")
    resume = workspace / "resumes" / "baselines" / "senior-defense-attorney.md"
    selection_guard.write_selection_seal(workspace, resume, previous, fake_review)

    blocked = _run(
        workspace,
        "verify",
        "resumes/baselines/senior-defense-attorney.md",
        "--refresh",
    )
    assert blocked.returncode == 2
    assert "strategy approval required" in blocked.stderr
    proposal = json.loads(
        (workspace / "build" / "revisions" / "senior-defense-attorney.strategy.json").read_text()
    )
    changes = proposal["blocking_changes"]
    assert changes["removed_role_ids"] == ["BBC-001"]
    assert "borscht-investigation" in changes["removed_story_ids"]
    assert set(plan_story.story_id for plan_story in plan.stories) - current_story_ids <= set(
        changes["removed_story_ids"]
    )


def test_phoenix_fixture_sources_are_locked_and_preserved() -> None:
    lock = json.loads((FIXTURE_ROOT / "bootstrap" / "source-lock.json").read_text())
    manifest = json.loads(
        (FIXTURE_ROOT / "workspace" / "vault" / "sources" / "manifest.json").read_text()
    )
    manifest_by_id = {source["id"]: source for source in manifest["sources"]}

    reproducible_ids: set[str] = set()
    for source in lock["sources"]:
        path = FIXTURE_ROOT / source["path"]
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        assert digest == source["sha256"]
        assert source["source_id"] == f"SRC-{digest[:12]}"
        assert manifest_by_id[source["source_id"]]["sha256"] == digest
        reproducible_ids.add(source["source_id"])

    preserved_ids: set[str] = set()
    for source in lock["preserved_snapshots"]:
        snapshot = FIXTURE_ROOT / source["snapshot"]
        assert hashlib.sha256(snapshot.read_bytes()).hexdigest() == source["snapshot_sha256"]
        assert manifest_by_id[source["source_id"]]["sha256"] == source["sha256"]
        preserved_ids.add(source["source_id"])

    assert set(manifest_by_id) == reproducible_ids | preserved_ids

    canonical = [
        *(FIXTURE_ROOT / "workspace" / "vault" / "facts").rglob("*.md"),
        *(FIXTURE_ROOT / "workspace" / "vault" / "employment").glob("*.md"),
    ]
    cited_ids = {
        source_id
        for path in canonical
        for source_id in SOURCE_ID.findall(path.read_text(encoding="utf-8"))
    }
    assert cited_ids <= reproducible_ids


def test_phoenix_fixture_rebuilds_from_locked_sources(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    initialization = _run(
        tmp_path,
        "init",
        "--workspace",
        str(workspace),
        "--storage",
        "local",
        "--git-name",
        "Fixture Test",
        "--git-email",
        "fixture@example.invalid",
    )
    assert initialization.returncode == 0, initialization.stderr or initialization.stdout

    lock = json.loads((FIXTURE_ROOT / "bootstrap" / "source-lock.json").read_text())
    sources = [str(FIXTURE_ROOT / source["path"]) for source in lock["sources"]]
    registration = _run(workspace, "hydrate", *sources, "--apply")
    assert registration.returncode == 0, registration.stderr or registration.stdout
    registration_result = json.loads(registration.stdout)
    assert registration_result["added"] == len(sources)

    plan = FIXTURE_ROOT / "bootstrap" / "hydration-plan.json"
    validation = _run(workspace, "plan", "validate", str(plan))
    assert validation.returncode == 0, validation.stderr or validation.stdout
    preview = _run(workspace, "plan", "preview", str(plan))
    assert preview.returncode == 0, preview.stderr or preview.stdout
    application = _run(workspace, "plan", "apply", str(plan))
    assert application.returncode == 0, application.stderr or application.stdout

    strict = _run(workspace, "validate", "--strict")
    assert strict.returncode == 0, strict.stderr or strict.stdout

    plan_data = json.loads(plan.read_text(encoding="utf-8"))
    approved_vault = FIXTURE_ROOT / "workspace" / "vault"
    for write in plan_data["writes"]:
        relative = Path(write["path"])
        assert (workspace / "vault" / relative).read_text(encoding="utf-8") == write["content"]
        assert (approved_vault / relative).read_text(encoding="utf-8") == write["content"]

    manifest = workspace / "vault" / "sources" / "manifest.json"
    manifest_before = hashlib.sha256(manifest.read_bytes()).hexdigest()
    repeated = _run(workspace, "hydrate", *sources, "--apply")
    assert repeated.returncode == 0, repeated.stderr or repeated.stdout
    repeated_result = json.loads(repeated.stdout)
    assert repeated_result["added"] == 0
    assert repeated_result["unchanged_exact_duplicates"] == len(sources)
    assert hashlib.sha256(manifest.read_bytes()).hexdigest() == manifest_before
