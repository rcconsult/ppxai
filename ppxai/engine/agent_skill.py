"""Agent skill directories (`/task` T4): launch a run from a mounted skill.

A *skill* is a directory that packages a reusable agent capability:

    skills/ci-triage/
      SKILL.md         # a spec (T3 front-matter): tool grant, budget, egress,
                       # body → system prompt
      references/*.md  # mounted into the run's READ-SCOPE (read_file/grep/
                       # search_files reach these; nothing else new)
      scripts/*.sh     # INERT — running them needs a shell grant + the
                       # container tier (T9); refused here

`--skill <name>` composes with T3: the skill's ``SKILL.md`` is parsed by the
T3 loader (:func:`ppxai.engine.agent_spec.load_spec_file`), so a skill is "a
spec file with a directory of references around it." The directory is then
added to the run's read-scope (T2 enforcement) so the agent can actually read
those references — and *only* those, not siblings outside the skill.

This module is pure resolution + loading. It does NOT apply precedence, union
grants, or enforce the operator ceiling — the server route
(`server/routes/agent_v1.py`) owns those trust-boundary decisions, exactly as
it does for specs. It refuses a skill whose ``scripts/`` a task would need
while ``allow_skill_scripts`` is off, but the *decision* to run scripts is not
this module's to make: it only reports the presence + the gate.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .agent_spec import AgentSpec, AgentSpecError, load_spec_file

# The manifest file that turns a directory into a skill. Same shape as a T3
# `.md` spec (YAML front-matter + body-as-system).
SKILL_MANIFEST = "SKILL.md"

# Sub-directory whose contents are mounted into the run read-scope.
REFERENCES_DIR = "references"

# Sub-directory of runnable scripts. INERT until the container tier (T9): a
# `/task` run has no shell grant, so these can never execute in the in-process
# tier. Detected only so a skill that *declares* it needs them is refused
# clearly rather than silently running defanged.
SCRIPTS_DIR = "scripts"


class AgentSkillError(ValueError):
    """A skill directory couldn't be resolved or loaded into a run."""


@dataclass
class LoadedSkill:
    """A resolved skill: its parsed manifest-spec + the paths T4 needs.

    ``read_root`` is the directory added to the run's read-scope (the skill
    dir itself, so both ``references/`` and the manifest are readable). The
    route unions ``spec.tools`` across skills and mounts each ``read_root``.
    """

    name: str
    root: str                 # absolute skill directory
    read_root: str            # dir mounted into read-scope (== root)
    spec: AgentSpec           # SKILL.md parsed via the T3 loader
    has_scripts: bool         # a non-empty scripts/ dir is present
    references: Optional[str] = None  # absolute references/ dir if present
    warnings: list = field(default_factory=list)


def _has_nonempty_dir(path: Path) -> bool:
    """True if `path` is a directory containing at least one entry."""
    try:
        return path.is_dir() and any(path.iterdir())
    except OSError:
        return False


def load_skill(root: Path, name: str) -> LoadedSkill:
    """Load a skill from an already-resolved directory.

    `root` MUST already be a validated directory inside the operator's
    ``skills_dir`` — this function does NOT do name→path resolution (the route
    owns that, so the traversal defence lives at the trust boundary). It reads
    ``SKILL.md`` through the T3 loader and inspects the directory layout.

    Raises :class:`AgentSkillError` if the directory has no ``SKILL.md`` or the
    manifest doesn't parse.
    """
    root = Path(root)
    manifest = root / SKILL_MANIFEST
    if not manifest.is_file():
        raise AgentSkillError(
            f"skill {name!r}: no {SKILL_MANIFEST} in {root}"
        )
    try:
        spec = load_spec_file(manifest)
    except AgentSpecError as exc:
        raise AgentSkillError(f"skill {name!r}: {exc}") from exc

    references = root / REFERENCES_DIR
    scripts = root / SCRIPTS_DIR
    has_scripts = _has_nonempty_dir(scripts)

    warnings = list(spec.warnings)
    if has_scripts:
        # Not fatal on its own — the route decides based on allow_skill_scripts.
        # Surface it so the operator sees the skill carries inert scripts.
        warnings.append(
            f"skill {name!r} contains a {SCRIPTS_DIR}/ dir; scripts are INERT "
            "in the in-process tier (need a shell grant + the container tier)"
        )

    return LoadedSkill(
        name=name,
        root=str(root),
        read_root=str(root),
        spec=spec,
        has_scripts=has_scripts,
        references=str(references) if references.is_dir() else None,
        warnings=warnings,
    )
