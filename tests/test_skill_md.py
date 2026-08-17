"""Guards against SKILL.md silently drifting from the pinned GDT version or
duplicating the schema instead of pointing at it (README -> SKILL.md outline).
"""

from __future__ import annotations

from pathlib import Path

from madflow_sqlops._version import GDT_TAG

SKILL_PATH = Path(__file__).parent.parent / ".claude" / "skills" / "madflow-sqlops" / "SKILL.md"


def _read_frontmatter_and_body() -> tuple[dict, str]:
    text = SKILL_PATH.read_text()
    assert text.startswith("---\n"), "SKILL.md must start with YAML frontmatter"
    _, frontmatter_text, body = text.split("---\n", 2)
    # Frontmatter here is flat `key: value` pairs only -- no need for a full
    # YAML parser (and a new dependency) for two lines.
    frontmatter = dict(
        line.split(":", 1) for line in frontmatter_text.strip().splitlines() if ":" in line
    )
    return {k.strip(): v.strip() for k, v in frontmatter.items()}, body


def test_skill_file_exists():
    assert SKILL_PATH.is_file()


def test_frontmatter_has_name_and_description():
    frontmatter, _ = _read_frontmatter_and_body()
    assert frontmatter["name"] == "madflow-sqlops"
    assert len(frontmatter["description"]) > 20


def test_body_documents_both_invocation_paths():
    _, body = _read_frontmatter_and_body()
    assert "madflow-sqlops tag" in body  # CLI
    assert "tag_operations" in body  # Python API


def test_body_references_the_pinned_gdt_tag():
    # Catches the doc silently going stale on a version bump -- if
    # _version.GDT_TAG changes, this fails until SKILL.md is updated too.
    _, body = _read_frontmatter_and_body()
    assert GDT_TAG in body


def test_body_points_at_the_schema_rather_than_duplicating_it():
    _, body = _read_frontmatter_and_body()
    assert "$schema" not in body
    assert "gdt-v0.1.schema.json" in body  # points at the vendored file, doesn't inline it
