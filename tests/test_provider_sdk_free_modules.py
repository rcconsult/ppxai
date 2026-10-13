"""ADR 0016 step 1: provider facts are readable without a provider SDK.

`ppxai/engine/providers/facts/` holds each provider's class-level facts
(`shipped_model_facts`, `default_capabilities`, `unmeasured_facts`,
`default_model_for_facts`) in modules that import no SDK, and the three
callers that read facts without an instance read them from there.

Two things are held here:

1. **No SDK in the import closure.** Walked statically over this repo's
   modules, starting from every facts module: no `openai`, `anthropic` or
   `google.genai` import, and no import of a provider implementation module
   or `providers.base` (which imports `openai` until step 2). Static,
   because at runtime the parent packages still load every SDK until
   steps 3 and 5 land; the runtime fences arrive with them.
2. **Parity with the classes.** For every registered name and for an
   unregistered one, `get_provider_facts(name)` gives exactly what the class
   the registry resolves carries, so moving the data changed no answer.
"""

import ast
from pathlib import Path

import pytest

from ppxai.engine import providers as _providers
from ppxai.engine.facts_resolver import provider_class_for
from ppxai.engine.providers.facts import _FACTS, get_provider_facts

REPO = Path(__file__).resolve().parents[1]
PKG = REPO / "ppxai"
FACTS_DIR = PKG / "engine" / "providers" / "facts"

SDK_ROOTS = ("openai", "anthropic", "google.genai")
FORBIDDEN_INTERNAL = (
    "ppxai.engine.providers.base",
    "ppxai.engine.providers.openai_native",
    "ppxai.engine.providers.openai_compat",
    "ppxai.engine.providers.gemini",
    "ppxai.engine.providers.anthropic",
)

FACT_ATTRS = (
    "shipped_model_facts",
    "default_capabilities",
    "unmeasured_facts",
    "default_model_for_facts",
)


def _module_name(path: Path) -> str:
    parts = list(path.relative_to(REPO).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _module_path(name: str) -> Path | None:
    base = REPO.joinpath(*name.split("."))
    for candidate in (base.with_suffix(".py"), base / "__init__.py"):
        if candidate.is_file():
            return candidate
    return None


def _imports(path: Path) -> set[str]:
    """Absolute names of every module-level and nested import in `path`."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    package = _module_name(path) if path.is_relative_to(REPO) else ""
    if path.name != "__init__.py":
        package = package.rpartition(".")[0]
    # `try: from . import _build_info / except ImportError` names a module
    # that may not exist (generated at build time); its package is not an
    # import of the package's `__init__`.
    optional = {
        id(inner)
        for node in ast.walk(tree) if isinstance(node, ast.Try)
        for inner in node.body if isinstance(inner, ast.ImportFrom)
    }
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                anchor = package.split(".")
                anchor = anchor[: len(anchor) - (node.level - 1)]
                base = ".".join(anchor + ([node.module] if node.module else []))
            else:
                base = node.module or ""
            # `from .. import facts_config` names a submodule: it loads that
            # module, and the package's `__init__` only as a parent. Parents
            # are not followed (they load every SDK until ADR 0016 steps 3
            # and 5), so a submodule import counts as the submodule alone.
            submodules = {
                f"{base}.{alias.name}" for alias in node.names
                if _module_path(f"{base}.{alias.name}") is not None
            }
            names.update(submodules)
            if len(submodules) < len(node.names) and id(node) not in optional:
                names.add(base)
    return names


def _closure(start: list[Path]) -> dict[str, set[str]]:
    """Every ppxai module reachable from `start`, mapped to what it imports."""
    seen: dict[str, set[str]] = {}
    todo = list(start)
    while todo:
        path = todo.pop()
        name = _module_name(path)
        if name in seen:
            continue
        seen[name] = _imports(path)
        for imported in seen[name]:
            if imported == "ppxai" or imported.startswith("ppxai."):
                target = _module_path(imported)
                if target is not None:
                    todo.append(target)
    return seen


FACTS_MODULES = sorted(FACTS_DIR.glob("*.py"))


class TestNoSdkInTheClosure:
    def test_the_facts_package_exists(self):
        assert {p.stem for p in FACTS_MODULES} >= {
            "__init__", "anthropic", "gemini", "openai_compat", "openai_native",
        }

    def test_no_sdk_is_reachable(self):
        offenders = [
            f"{module} imports {imported}"
            for module, imported_names in _closure(FACTS_MODULES).items()
            for imported in imported_names
            if any(imported == r or imported.startswith(r + ".") for r in SDK_ROOTS)
        ]
        assert not offenders, (
            "A provider facts module reaches a provider SDK, so reading facts "
            "would load it (ADR 0016 §3). Move the data, not the import:\n  "
            + "\n  ".join(sorted(offenders))
        )

    def test_no_provider_implementation_is_reachable(self):
        offenders = [
            f"{module} imports {imported}"
            for module, imported_names in _closure(FACTS_MODULES).items()
            for imported in imported_names
            if imported in FORBIDDEN_INTERNAL
        ]
        assert not offenders, (
            "A provider facts module imports a provider implementation or "
            "providers.base. Facts are data the classes read, never the "
            "reverse:\n  " + "\n  ".join(sorted(offenders))
        )

    def test_the_walk_sees_a_planted_sdk_import(self, tmp_path):
        """Control: the walker reports an SDK import when one is there."""
        planted = tmp_path / "planted.py"
        planted.write_text("import openai\nfrom google.genai import types\n")
        assert {"openai", "google.genai"} <= _imports(planted)


class TestParityWithTheClasses:
    @pytest.mark.parametrize("name", sorted(_FACTS) + ["openrouter", "no-such-provider"])
    def test_facts_match_the_class_that_serves_the_name(self, name):
        cls = provider_class_for(name)
        record = get_provider_facts(name)
        for attr in FACT_ATTRS:
            assert getattr(record, attr) == getattr(cls, attr, None), (
                f"{name}: get_provider_facts().{attr} differs from "
                f"{cls.__name__}.{attr}"
            )

    def test_every_registered_name_has_a_facts_row(self):
        registered = set(_providers.list_registered_providers())
        assert registered <= set(_FACTS), (
            "A provider is registered with no row in providers/facts/_FACTS, "
            f"so its facts would resolve to the fallback: {sorted(registered - set(_FACTS))}"
        )

    @pytest.mark.parametrize("name", sorted(_FACTS))
    def test_the_class_reads_the_same_objects(self, name):
        """The class attributes ARE the facts module's objects, not copies."""
        cls = _providers.get_provider_class(name)
        if cls is None:
            pytest.skip(f"{name} is not registered (its SDK is not installed)")
        record = get_provider_facts(name)
        assert cls.default_capabilities is record.default_capabilities

