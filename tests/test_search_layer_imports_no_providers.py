"""ADR 0014 Decision 1: `ppxai/engine/search/` imports nothing from
`ppxai.engine.providers`.

The search layer (backends + resolver) is meant to outlive any one chat
provider — ADR 0015 removes the Perplexity chat provider while the
Perplexity SEARCH backend stays, which only holds if the search package
never reaches back into `providers`. This is the same shape as
`tests/test_no_new_lazy_imports.py::TestEngineImportsNoCommands` (`engine`
-> `commands`), applied to the new `search` -> `providers` edge: module
scope AND function level, walked via `ast` rather than grepped, with a
guard-first structure so a detector that stopped matching cannot pass
silently.
"""

import ast
import pathlib

PPXAI = pathlib.Path(__file__).resolve().parent.parent / "ppxai"
SEARCH_ROOT = PPXAI / "engine" / "search"


def _package_of(module: str, is_init: bool) -> str:
    """The package a module lives in (itself, if it's an `__init__`)."""
    return module if is_init else module.rsplit(".", 1)[0]


def _module_name(path: pathlib.Path, root: pathlib.Path) -> str:
    """Dotted module name for `path`. Real search-tree files resolve
    relative to the repo root (`ppxai.engine.search....`); a planted
    synthetic file under a pytest `tmp_path` (never under the repo) gets a
    fake `search.<name>` module name — enough for `_resolve` to compute a
    relative import correctly, which is all the guard tests below need."""
    try:
        rel = path.relative_to(PPXAI.parent).with_suffix("")
        parts = list(rel.parts)
    except ValueError:
        rel = path.relative_to(root).with_suffix("")
        parts = ["ppxai", "engine", "search", *rel.parts]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _resolve(node: ast.ImportFrom, module: str, is_init: bool) -> str | None:
    """Absolute dotted target of an ImportFrom, or None for a plain `import`."""
    level = node.level or 0
    if level == 0:
        return node.module
    base = _package_of(module, is_init).split(".")
    up = level - 1
    if up:
        base = base[:-up] if up <= len(base) else []
    return ".".join(base + ([node.module] if node.module else []))


def _search_to_providers_edges(root: pathlib.Path = SEARCH_ROOT) -> list[tuple[str, str, int]]:
    """`(module, target, lineno)` for every `search -> providers` import,
    module scope AND function level — a function-level import closes the
    same edge, just later.
    """
    found: list[tuple[str, str, int]] = []
    for path in sorted(root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        module = _module_name(path, root)
        is_init = path.name == "__init__.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == "ppxai.engine.providers" or alias.name.startswith(
                        "ppxai.engine.providers."
                    ):
                        found.append((module, alias.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = _resolve(node, module, is_init)
                if target and (
                    target == "ppxai.engine.providers"
                    or target.startswith("ppxai.engine.providers.")
                ):
                    found.append((module, target, node.lineno))
                elif target == "ppxai.engine":
                    for alias in node.names:
                        if alias.name == "providers":
                            found.append(
                                (module, "ppxai.engine.providers", node.lineno)
                            )
                elif target == "ppxai":
                    # `from .. import providers` two levels up, in principle
                    # reachable from a deeply nested search submodule.
                    for alias in node.names:
                        if alias.name == "providers":
                            found.append(
                                (module, "ppxai.providers", node.lineno)
                            )
    return found


class TestDetectorCatchesAPlantedViolation:
    """Guard first: prove the checker flags a violation before trusting it
    to report a clean tree as clean. Parses a SYNTHETIC source string —
    never touches the real `search/` tree — so a broken checker cannot
    pass by accident."""

    def test_module_scope_from_import_is_flagged(self, tmp_path):
        src = "from ppxai.engine.providers.perplexity import PerplexityProvider\n"
        planted = tmp_path / "planted.py"
        planted.write_text(src, encoding="utf-8")
        edges = _search_to_providers_edges(tmp_path)
        assert edges, "planted module-scope violation was not detected"
        assert edges[0][1].startswith("ppxai.engine.providers")

    def test_relative_import_is_flagged(self, tmp_path):
        # As it would read from inside ppxai/engine/search/perplexity.py:
        # `from ..providers.perplexity_facts import AGENT_FLEET_FACTS`
        src = "from ..providers.perplexity_facts import AGENT_FLEET_FACTS\n"
        planted = tmp_path / "engine_search_planted.py"
        planted.write_text(src, encoding="utf-8")
        # `_module_name` needs a path under PPXAI.parent to resolve a dotted
        # module name; fake one directly rather than relying on tmp_path
        # sitting under the repo.
        module = "ppxai.engine.search.planted"
        tree = ast.parse(src)
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        target = _resolve(node, module, is_init=False)
        assert target == "ppxai.engine.providers.perplexity_facts"

    def test_function_level_import_is_also_flagged(self, tmp_path):
        src = (
            "def f():\n"
            "    from ppxai.engine.providers.perplexity import PerplexityProvider\n"
            "    return PerplexityProvider\n"
        )
        planted = tmp_path / "planted_fn.py"
        planted.write_text(src, encoding="utf-8")
        edges = _search_to_providers_edges(tmp_path)
        assert edges, "planted function-level violation was not detected"

    def test_a_clean_file_reports_nothing(self, tmp_path):
        src = "from ppxai.engine.types import ToolUsage\n"
        clean = tmp_path / "clean.py"
        clean.write_text(src, encoding="utf-8")
        assert _search_to_providers_edges(tmp_path) == []


def test_the_search_package_exists_where_we_think():
    assert SEARCH_ROOT.is_dir(), "wrong root? ppxai/engine/search/ not found"
    assert (SEARCH_ROOT / "resolver.py").exists()
    assert (SEARCH_ROOT / "perplexity_facts.py").exists()


def test_search_layer_imports_nothing_from_providers():
    """The real assertion (ADR 0014 Decision 1): zero edges from the actual
    `ppxai/engine/search/` tree into `ppxai.engine.providers`, at module
    scope or inside a function."""
    edges = _search_to_providers_edges()
    assert edges == [], (
        "ppxai/engine/search/ must not import ppxai.engine.providers "
        f"(ADR 0014 Decision 1); found: {edges}"
    )
