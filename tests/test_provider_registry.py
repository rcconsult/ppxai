"""The provider registry is data, loaded through one function (ADR 0016 §1, §2, §7).

`ppxai/engine/providers/__init__.py` declares `_PROVIDER_MODULES` and
`_FALLBACK` and imports a provider module only when that provider is first
needed. Four things keep that honest:

- `importlib.import_module` is called only at the declared load points, so
  the table stays the readable dependency list the no-lazy-imports rule
  wants;
- every PyInstaller spec that bundles the engine lists every table module,
  because PyInstaller cannot follow an `importlib` call (a missing entry
  breaks a binary at provider-switch time, not at build time);
- every entry resolves to a `BaseProvider` subclass, the same object a
  direct import yields (ppxai-sre's seam test asserts that identity);
- importing the engine loads no provider module but `base`, and neither the
  Anthropic nor the Google SDK.
"""

from __future__ import annotations

import ast
import re
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from ppxai.engine import providers
from ppxai.engine.providers import (
    _FALLBACK,
    _PROVIDER_MODULES,
    create_provider,
    fallback_provider_class,
    get_provider_class,
    load_provider_class,
)
from ppxai.engine.providers.base import BaseProvider

REPO = Path(__file__).resolve().parent.parent
PKG = REPO / "ppxai"

#: (file relative to ppxai/, enclosing function) -> why it may call
#: `importlib.import_module`. ADR 0016 §7 names these; add one only with an
#: ADR saying why.
ALLOWED_IMPORT_MODULE_SITES = {
    ("commands/factory.py", "_ensure_loaded"): "ADR 0007: _BUILTIN_COMMAND_MODULES",
    ("commands/factory.py", "reload_user_commands"): "user command files, not ppxai modules",
    ("engine/providers/__init__.py", "_import"): "ADR 0016: _PROVIDER_MODULES",
}

#: Specs whose binary runs the engine. ppxai-desktop is a launcher that
#: excludes it.
ENGINE_SPECS = ["ppxai.spec", "ppxai-server.spec", "ppxaide.spec"]

REGISTRY_MODULES = sorted({m for m, _ in _PROVIDER_MODULES.values()} | {_FALLBACK[0]})


def _sites_in(source: str, rel: str) -> list[tuple[str, str, int]]:
    """`import_module` calls in `source`, with their enclosing function."""
    sites = []

    def visit(node, func):
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                visit(child, child.name)
                continue
            if (isinstance(child, ast.Call)
                    and isinstance(child.func, ast.Attribute)
                    and child.func.attr == "import_module"):
                sites.append((rel, func, child.lineno))
            visit(child, func)

    visit(ast.parse(source), "<module>")
    return sites


def _import_module_sites() -> list[tuple[str, str, int]]:
    sites = []
    for path in sorted(PKG.rglob("*.py")):
        sites += _sites_in(path.read_text(encoding="utf-8"), path.relative_to(PKG).as_posix())
    return sites


def _spec_strings(spec: str) -> set[str]:
    return set(re.findall(r"['\"](ppxai(?:\.[A-Za-z0-9_]+)+)['\"]", (REPO / spec).read_text(encoding="utf-8")))


class TestOneLoadPoint:
    def test_import_module_only_at_declared_sites(self):
        stray = [f"ppxai/{rel}:{line} in {func}()"
                 for rel, func, line in _import_module_sites()
                 if (rel, func) not in ALLOWED_IMPORT_MODULE_SITES]
        assert not stray, (
            "importlib.import_module outside the declared load points (ADR 0016 §7). "
            "Import the module at the top of the file, or add the module to a "
            "declared table such as providers._PROVIDER_MODULES:\n  " + "\n  ".join(stray))

    def test_every_allowed_site_still_exists(self):
        found = {(rel, func) for rel, func, _ in _import_module_sites()}
        stale = set(ALLOWED_IMPORT_MODULE_SITES) - found
        assert not stale, f"Remove these rows from ALLOWED_IMPORT_MODULE_SITES: {sorted(stale)}"

    def test_a_planted_site_is_caught(self):
        """Control: the scan sees a call nested in a function, by name."""
        planted = textwrap.dedent("""
            import importlib
            class C:
                def sneaky(self):
                    if True:
                        return importlib.import_module("x")
        """)
        assert _sites_in(planted, "planted.py") == [("planted.py", "sneaky", 6)]


class TestPyInstallerParity:
    @pytest.mark.parametrize("spec", ENGINE_SPECS)
    def test_every_registry_module_is_a_hiddenimport(self, spec):
        missing = [m for m in REGISTRY_MODULES if m not in _spec_strings(spec)]
        assert not missing, (
            f"{spec} does not list {missing} in hiddenimports. Providers load "
            "through importlib (ADR 0016), which PyInstaller cannot follow, so "
            "the binary would fail when that provider is created.")

    @pytest.mark.parametrize("spec", ENGINE_SPECS + ["ppxai-desktop.spec"])
    def test_no_spec_names_a_provider_module_that_does_not_exist(self, spec):
        gone = []
        for name in _spec_strings(spec):
            if not name.startswith("ppxai.engine.providers."):
                continue
            rel = Path(*name.split("."))
            if not ((REPO / rel).with_suffix(".py").exists() or (REPO / rel / "__init__.py").exists()):
                gone.append(name)
        assert not gone, f"{spec} names provider modules that no longer exist: {sorted(gone)}"


class TestEveryEntryResolves:
    @pytest.mark.parametrize("name", sorted(_PROVIDER_MODULES))
    def test_entry_is_a_base_provider(self, name):
        cls = load_provider_class(name)
        assert issubclass(cls, BaseProvider)

    @pytest.mark.parametrize("name", sorted(_PROVIDER_MODULES))
    def test_registered_class_is_the_module_attribute(self, name):
        """Same object as a direct import, not a copy (ppxai-sre's seam test)."""
        cls = get_provider_class(name)
        if cls is None:
            pytest.skip(f"{name}: its optional SDK is not installed")
        module, attr = _PROVIDER_MODULES[name]
        if cls is fallback_provider_class():
            return  # gemini without google-genai
        assert cls is getattr(sys.modules[module], attr)

    def test_an_unregistered_name_gets_the_fallback(self):
        assert get_provider_class("openrouter") is None
        assert load_provider_class("openrouter") is fallback_provider_class()
        provider = create_provider("openrouter", api_key="k", base_url="http://127.0.0.1:9/v1")
        assert type(provider) is fallback_provider_class()
        assert provider.provider_id == "openrouter"

    def test_the_fallback_is_openai_compatible(self):
        assert _FALLBACK == ("ppxai.engine.providers.openai_compat", "OpenAICompatibleProvider")

    def test_loads_are_cached(self, monkeypatch):
        load_provider_class("openai")
        calls = []
        monkeypatch.setattr(providers, "_import", lambda entry: calls.append(entry))
        load_provider_class("openai")
        assert calls == []


def _loaded_after(code: str) -> list[str]:
    probe = textwrap.dedent(f"""
        import sys
        {code}
        mods = sorted(m for m in sys.modules
                      if m in ("anthropic", "google.genai")
                      or m in {REGISTRY_MODULES + ["ppxai.engine.providers.gemini",
                                                    "ppxai.engine.providers.anthropic"]!r})
        print("LOADED=" + ",".join(mods))
    """)
    out = subprocess.run([sys.executable, "-c", probe], capture_output=True, text=True,
                         timeout=120, cwd=REPO)
    assert out.returncode == 0, out.stderr
    line = [ln for ln in out.stdout.splitlines() if ln.startswith("LOADED=")]
    assert line, f"probe printed nothing: {out.stdout!r} {out.stderr!r}"
    return [m for m in line[-1][len("LOADED="):].split(",") if m]


class TestNothingLoadsUntilAsked:
    def test_importing_the_engine_loads_no_provider_module(self):
        assert _loaded_after("import ppxai.engine") == []

    def test_a_probe_sees_a_load(self):
        """Control: the probe would notice a provider module being loaded."""
        loaded = _loaded_after(
            "from ppxai.engine.providers import load_provider_class; load_provider_class('openai')")
        assert "ppxai.engine.providers.openai_native" in loaded

    def test_the_gemini_class_loads_no_anthropic(self):
        loaded = _loaded_after(
            "from ppxai.engine.providers import load_provider_class; load_provider_class('gemini')")
        assert "anthropic" not in loaded
        assert "ppxai.engine.providers.anthropic" not in loaded
