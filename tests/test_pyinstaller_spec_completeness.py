"""Regression guard: PyInstaller specs must list every module that
`CommandFactory._ensure_loaded` loads dynamically.

Backstory
---------
In v1.17.4 the command system was refactored from explicit static
imports (`from . import session, provider, ...` in handler.py) to
dynamic loading via `importlib.import_module(string)` in factory.py
(`_ensure_loaded`). PyInstaller's static analyzer can't see dynamic
string imports, so the frozen binaries silently dropped 9 of the 10
command modules from every release v1.17.4 → v1.18.0. Only `/usage`
in the web app actually exercised the broken `POST /command/` path
(everything else routes through dedicated endpoints), so the bug
went undetected for six releases on every platform.

This test reads each PyInstaller spec file and asserts the module
list in `_BUILTIN_COMMAND_MODULES` is fully present in `hiddenimports`.
A single missing entry fails the test with a clear message naming
the spec + module.

Coverage
--------
- ppxai-server.spec  → MUST have all builtins (web/VSCode hits POST /command/)
- ppxaide.spec       → MUST have all builtins (Textual TUI uses CommandFactory)
- ppxai.spec         → MUST have all builtins (Rich TUI uses CommandFactory)
- ppxai-desktop.spec → SKIPPED (spawns ppxai-server.exe, doesn't import commands itself)
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]


def _read_spec(spec_name: str) -> str:
    """Return the full text of a PyInstaller spec file."""
    return (REPO_ROOT / spec_name).read_text(encoding="utf-8")


def _builtin_modules() -> tuple[str, ...]:
    """Read `_BUILTIN_COMMAND_MODULES` from `ppxai/commands/factory.py`.

    Imports the module so the test can't drift from what the factory
    actually loads. If you add a module to the tuple, the test
    automatically picks it up — and the corresponding hiddenimport
    check fails until you add it to the specs.
    """
    from ppxai.commands.factory import _BUILTIN_COMMAND_MODULES

    return tuple(_BUILTIN_COMMAND_MODULES)


# Specs that pack a Python interpreter and run `CommandFactory.get(name)`
# at runtime. Each must include every dynamically-loaded command module
# in its `hiddenimports` block.
SPECS_WITH_COMMANDS = ["ppxai-server.spec", "ppxai.spec", "ppxaide.spec"]


@pytest.mark.parametrize("spec_name", SPECS_WITH_COMMANDS)
def test_spec_lists_every_builtin_command_module(spec_name: str) -> None:
    """The spec's hiddenimports must reference every builtin command module.

    Without these explicit listings, PyInstaller's static analyzer
    can't see the dynamic `importlib.import_module(string)` calls
    in factory.py, the modules don't end up in the frozen bundle,
    and `CommandFactory._registry` is empty at runtime.
    """
    spec_text = _read_spec(spec_name)
    missing = []
    for module in _builtin_modules():
        # Match the literal string `'ppxai.commands.<name>'` anywhere
        # in the spec — quoting style doesn't matter, comments fine.
        needle = f"ppxai.commands.{module}"
        if needle not in spec_text:
            missing.append(module)

    if missing:
        msg_lines = [
            f"{spec_name} is missing hidden imports for "
            f"{len(missing)} command module(s) loaded by "
            f"CommandFactory._ensure_loaded:",
            "",
        ]
        for m in missing:
            msg_lines.append(f"  - 'ppxai.commands.{m}'")
        msg_lines += [
            "",
            "Add each of these to the spec's `hiddenimports` list.",
            "PyInstaller can't see them because factory.py loads them",
            "via dynamic strings (`importlib.import_module(f'.{name}',",
            "package='ppxai.commands')`).",
        ]
        pytest.fail("\n".join(msg_lines))


def test_spec_does_not_drift_from_factory_module_list() -> None:
    """The factory's _BUILTIN_COMMAND_MODULES tuple is the authority.

    This sentinel test fails loudly if the tuple shrinks — meaning a
    module was removed from the factory but the specs still list it
    (cosmetic, no runtime issue). Keeps the spec entries tidy.
    """
    builtin = _builtin_modules()
    assert len(builtin) >= 10, (
        f"Builtin command module list shrank below 10 entries "
        f"({len(builtin)} found). If the change is intentional, "
        f"update this sentinel and the relevant spec files. "
        f"Current modules: {builtin}"
    )


def test_at_least_session_provider_system_present() -> None:
    """Sanity: the most basic commands that every user hits MUST be in
    the builtin list. Catches an accidental tuple replacement that
    removes everything but leaves it non-empty.
    """
    builtin = _builtin_modules()
    for must_have in ("session", "provider", "system"):
        assert must_have in builtin, (
            f"Expected '{must_have}' in _BUILTIN_COMMAND_MODULES, "
            f"got {builtin}. Did the factory's loader contract change?"
        )


# ── Provider modules (2026-10-11) ─────────────────────────────────────────
# The specs named `ppxai.engine.providers.perplexity` long after ADR 0015
# deleted it, and never named `openai_native` or `anthropic`. Harmless only
# while `providers/__init__.py` imports every provider statically; ADR 0016
# (v1.19.5) makes that loading dynamic, and then a missing entry breaks a
# binary at provider-switch time.

PROVIDERS_DIR = REPO_ROOT / "ppxai" / "engine" / "providers"
SPECS_WITH_PROVIDERS = ["ppxai-server.spec", "ppxai.spec"]


def _provider_modules() -> set[str]:
    return {
        f"ppxai.engine.providers.{p.stem}"
        for p in PROVIDERS_DIR.glob("*.py") if p.stem != "__init__"
    }


def _spec_provider_entries(spec_name: str) -> set[str]:
    return set(re.findall(r"'(ppxai\.engine\.providers\.[a-z_]+)'", _read_spec(spec_name)))


@pytest.mark.parametrize("spec_name", SPECS_WITH_PROVIDERS)
def test_spec_names_every_provider_module(spec_name: str) -> None:
    missing = _provider_modules() - _spec_provider_entries(spec_name)
    assert not missing, (
        f"{spec_name} hiddenimports lack {sorted(missing)}; add them, or the "
        "binary cannot load that provider once loading is dynamic (ADR 0016)"
    )


@pytest.mark.parametrize("spec_name", SPECS_WITH_PROVIDERS)
def test_spec_names_no_deleted_provider_module(spec_name: str) -> None:
    stale = _spec_provider_entries(spec_name) - _provider_modules()
    assert not stale, f"{spec_name} names provider modules that no longer exist: {sorted(stale)}"


ALL_SPECS = ["ppxai-server.spec", "ppxai.spec", "ppxaide.spec", "ppxai-desktop.spec"]


def _module_exists(dotted: str) -> bool:
    path = REPO_ROOT.joinpath(*dotted.split("."))
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


@pytest.mark.parametrize("spec_name", ALL_SPECS)
def test_every_ppxai_hiddenimport_exists(spec_name: str) -> None:
    """A retired module lingers in a spec as build-log ERROR noise, and hides
    a real gap in the same list: `ppxai.engine.model_profiles` sat in
    ppxai-server.spec after Item 65 retired it (found 2026-10-11)."""
    named = set(re.findall(r"'(ppxai(?:\.[a-z_0-9]+)+)'", _read_spec(spec_name)))
    # `ppxai.py` is the entry script Analysis() takes, not a module name.
    gone = sorted(m for m in named if not m.endswith(".py") and not _module_exists(m))
    assert not gone, f"{spec_name} hiddenimports name modules that no longer exist: {gone}"
