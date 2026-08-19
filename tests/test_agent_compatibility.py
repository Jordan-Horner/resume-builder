from __future__ import annotations

from pathlib import Path

import yaml

ROOT = Path(__file__).parents[1]
CANONICAL_SKILLS = ROOT / ".agents" / "skills"
CLAUDE_SKILLS = ROOT / ".claude" / "skills"


def _frontmatter(path: Path) -> dict[str, object]:
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _, raw, _ = text.split("---", 2)
    value = yaml.safe_load(raw)
    assert isinstance(value, dict)
    return value


def test_claude_imports_the_canonical_repository_instructions() -> None:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")

    assert text.splitlines()[0] == "@AGENTS.md"
    assert "`AGENTS.md` is the canonical repository instruction file" in text
    assert "every substantive workflow remains canonical" in text


def test_every_canonical_skill_has_a_non_divergent_claude_adapter() -> None:
    canonical = {path.parent.name: path for path in CANONICAL_SKILLS.glob("*/SKILL.md")}
    adapters = {path.parent.name: path for path in CLAUDE_SKILLS.glob("*/SKILL.md")}

    assert adapters.keys() == canonical.keys()
    for name, canonical_path in canonical.items():
        adapter_path = adapters[name]
        canonical_metadata = _frontmatter(canonical_path)
        adapter_metadata = _frontmatter(adapter_path)
        assert adapter_metadata == {
            "name": canonical_metadata["name"],
            "description": canonical_metadata["description"],
        }
        adapter = adapter_path.read_text(encoding="utf-8")
        relative = f"../../../.agents/skills/{name}/SKILL.md"
        assert relative in adapter
        assert (adapter_path.parent / relative).resolve() == canonical_path.resolve()
        assert "authoritative workflow" in adapter
        assert len(adapter.splitlines()) <= 14
