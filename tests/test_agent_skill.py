"""Tests for the T4 skill loader — `ppxai.engine.agent_skill`.

A skill is a directory: SKILL.md (a T3 spec) + references/ (mounted into the
run read-scope) + scripts/ (inert). This module is pure resolution + loading;
it does NOT do name→path resolution (the route owns the traversal defence) or
enforce the ceiling. These tests exercise the loading contract only.
"""

from __future__ import annotations

import pytest

from ppxai.engine.agent_skill import (
    AgentSkillError,
    LoadedSkill,
    load_skill,
    REFERENCES_DIR,
    SCRIPTS_DIR,
    SKILL_MANIFEST,
)


def _make_skill(root, manifest_text, *, references=None, scripts=None):
    """Build a skill dir on disk. references/scripts are lists of filenames."""
    root.mkdir(parents=True, exist_ok=True)
    (root / SKILL_MANIFEST).write_text(manifest_text, encoding="utf-8")
    if references is not None:
        rdir = root / REFERENCES_DIR
        rdir.mkdir()
        for name in references:
            (rdir / name).write_text("ref\n", encoding="utf-8")
    if scripts is not None:
        sdir = root / SCRIPTS_DIR
        sdir.mkdir()
        for name in scripts:
            (sdir / name).write_text("#!/bin/sh\necho hi\n", encoding="utf-8")
    return root


class TestLoadSkill:
    def test_manifest_parsed_as_spec(self, tmp_path):
        root = _make_skill(
            tmp_path / "ci-triage",
            "---\ntools: [read_file, grep]\nprovider: p\nmodel: m\n"
            "budget: {iterations: 5}\n---\nYou triage CI failures.\n",
        )
        skill = load_skill(root, "ci-triage")
        assert isinstance(skill, LoadedSkill)
        assert skill.name == "ci-triage"
        assert skill.spec.tools == ["read_file", "grep"]
        assert skill.spec.provider == "p" and skill.spec.model == "m"
        assert skill.spec.budget == {"iterations": 5}
        # Body → system prompt (T3 md semantics).
        assert skill.spec.system == "You triage CI failures."

    def test_read_root_is_skill_dir(self, tmp_path):
        root = _make_skill(tmp_path / "s", "---\ntools: [read_file]\n---\nx\n",
                           references=["checklist.md"])
        skill = load_skill(root, "s")
        assert skill.read_root == str(root)
        assert skill.references == str(root / REFERENCES_DIR)

    def test_references_absent_is_none(self, tmp_path):
        root = _make_skill(tmp_path / "s", "---\ntools: [read_file]\n---\nx\n")
        skill = load_skill(root, "s")
        assert skill.references is None

    def test_missing_manifest_raises(self, tmp_path):
        root = tmp_path / "no-manifest"
        root.mkdir()
        (root / REFERENCES_DIR).mkdir()
        with pytest.raises(AgentSkillError) as ei:
            load_skill(root, "no-manifest")
        assert SKILL_MANIFEST in str(ei.value)

    def test_malformed_manifest_raises_skill_error(self, tmp_path):
        # A manifest that the T3 loader rejects surfaces as AgentSkillError, not
        # a raw AgentSpecError — the skill layer wraps it with the skill name.
        root = _make_skill(tmp_path / "bad", "---\ntools: 123\n---\nx\n")
        # `tools: 123` is neither list nor string → AgentSpecError inside.
        with pytest.raises(AgentSkillError) as ei:
            load_skill(root, "bad")
        assert "bad" in str(ei.value)


class TestScriptsDetection:
    def test_nonempty_scripts_flagged(self, tmp_path):
        root = _make_skill(tmp_path / "s", "---\ntools: [read_file]\n---\nx\n",
                           scripts=["run.sh"])
        skill = load_skill(root, "s")
        assert skill.has_scripts is True
        assert any(SCRIPTS_DIR in w for w in skill.warnings)

    def test_empty_scripts_dir_not_flagged(self, tmp_path):
        root = _make_skill(tmp_path / "s", "---\ntools: [read_file]\n---\nx\n")
        (root / SCRIPTS_DIR).mkdir()  # present but empty
        skill = load_skill(root, "s")
        assert skill.has_scripts is False

    def test_no_scripts_dir_not_flagged(self, tmp_path):
        root = _make_skill(tmp_path / "s", "---\ntools: [read_file]\n---\nx\n")
        skill = load_skill(root, "s")
        assert skill.has_scripts is False
