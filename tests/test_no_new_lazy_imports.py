"""No NEW internal lazy imports (project rule; step 1 of the cleanup).

`docs/patterns/protocol-dependency-inversion.md` is marked **CRITICAL** and
says "NEVER use `TYPE_CHECKING` — it's a lazy import in disguise". A
function-level `from ..config import X` is the same evasion spelled
differently: it hides a dependency from the module graph, so the real shape
of the codebase cannot be read from its imports.

The rule already existed and nothing enforced it, which is how the count
reached triple digits. This fence does not fix them — steps 2 and 3 do — it
stops the number growing while that work happens.

**The baseline is a data set, not a count.** `len(found) <= 97` would pass
while one import is fixed and a worse one added. Pinning `(module, target)`
pairs makes a swap fail, and makes every removal show up as a diff to this
file — which is the record of the cleanup.

**Three categories are deliberately NOT counted**, or the fence would fight
correct code:

- `try: import x / except ImportError` optional-dependency guards. Deferring
  is the entire point of an optional dependency.
- stdlib and third-party imports inside functions. Deferring a heavy import
  for startup cost is a legitimate choice, unrelated to cycles.
- a package `__init__` importing its own submodules. That is how a package
  re-exports; it is not an evasion.

**Of the 97 pairs, 89 hoist cleanly and 8 genuinely cycle** — measured by
actually hoisting each one and importing the module in a fresh interpreter,
not by reading the graph. The 8 are step 3's structural work.

**"Imports cleanly" is necessary but NOT sufficient.** Hoisting moves name
resolution from call time to import time, so a test doing
`patch.object(source_module, name)` or `monkeypatch.setattr(...)` stops
reaching it — the module imports fine and the test fails. 25 rows are kept
for this reason. Run the tests, not just an import check.

Two traps worth not rediscovering: a sweep for `patch`/`patch.object` alone
misses `monkeypatch.setattr` and reports those rows as safe; and a bare
`import ppxai.tui.*` hangs (Textual sets up the terminal at import) on a
clean tree as much as a modified one, so verify TUI modules with the suite.
"""

import ast
import pathlib

import pytest

PPXAI = pathlib.Path(__file__).resolve().parent.parent / "ppxai"

#: Rows retained ON PURPOSE, with the reason. Everything in `BASELINE` that
#: is NOT here is simply "not hoisted yet" — step 2 work still to do.
#:
#: Without this split, step 3 inherits the whole baseline with no way to tell
#: "nobody got to it" from "moving this would break something", and the
#: obvious next action (hoist the rest) is wrong for these.
RETAINED_ON_PURPOSE = {
    # --- genuine import cycles (8) -------------------------------------
    # Hoisting raises ImportError from a partially initialized module.
    # Step 3 fixes these structurally, via a Protocol in a leaf module.
    ("ppxai.config.execution", "ppxai.engine.facts_resolver"): "cycle",
    ("ppxai.engine.facts_resolver", "ppxai.engine.providers"): "patch-semantics",
    ("ppxai.engine.task_authorizer", "ppxai.engine.facts_resolver"): "patch-semantics",
    ("ppxai.engine.task_authorizer", "ppxai.engine.providers"): "patch-semantics",
    ("ppxai.common.consent", "ppxai.engine.tools.wrappers"): "cycle",
    ("ppxai.config.execution", "ppxai.engine.model_facts"): "cycle",
    ("ppxai.config.loader", "ppxai.config.tls"): "cycle",
    ("ppxai.rendering.rich_renderer", "ppxai.common.markdown_links"): "cycle",
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"): "cycle",
    ("ppxai.rendering.textual_renderer", "ppxai.common.markdown_links"): "cycle",
    # --- patch semantics (25) ------------------------------------------
    # Hoisting binds the name at import time, so a test patching it on the
    # source module stops reaching it. Grep the imported name in tests/ to
    # see which test.
    ("ppxai.commands.doctor", "ppxai.config"): "patch-semantics",
    ("ppxai.commands.doctor", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.config.execution", "ppxai.config.tools"): "patch-semantics",
    ("ppxai.engine.providers.base", "ppxai.config.facts_config"): "patch-semantics",
    ("ppxai.engine.providers.gemini", "ppxai.usage"): "patch-semantics",
    ("ppxai.engine.providers.openai_compat", "ppxai.usage"): "patch-semantics",
    ("ppxai.engine.providers.openai_native", "ppxai.usage"): "patch-semantics",
    ("ppxai.engine.providers.perplexity", "ppxai.usage"): "patch-semantics",
    ("ppxai.engine.providers.wire.responses", "ppxai.usage"): "patch-semantics",
    ("ppxai.engine.task_authorizer", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.engine.task_backend", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.engine.tools.network_policy", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.engine.tools.search_backends", "ppxai.config"): "patch-semantics",
    ("ppxai.server.auth", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.server.http", "ppxai.config.loader"): "patch-semantics",
    ("ppxai.server.routes.agent_v1", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.server.routes.config", "ppxai.config"): "patch-semantics",
    ("ppxai.server.routes.config", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.server.routes.files", "ppxai.engine.tools.builtin.pptx_tools"): "patch-semantics",
    ("ppxai.server.routes.oneshot", "ppxai.server.routes.agent_v1"): "patch-semantics",
    ("ppxai.server.routes.sessions", "ppxai.config.execution"): "patch-semantics",
    ("ppxai.server.routes.sessions", "ppxai.server.auth"): "patch-semantics",
    # --- empty block (1) -----------------------------------------------
    # Sole statement of its block: removing it leaves `try:` with no body,
    # and an import alone in a try is deliberately conditional.
    ("ppxai.commands.handler", "ppxai.rendering.rich_renderer"): "empty-block",
}

#: Internal function-level imports present when the fence was written,
#: measured at `12a2c9b7`. Every entry is a known violation awaiting steps
#: 2 and 3 — REMOVE rows as they are fixed; never add one.
BASELINE = {
    ("ppxai.commands.handler", "ppxai.rendering.rich_renderer"),
    ("ppxai.commands.doctor", "ppxai.config"),
    ("ppxai.commands.doctor", "ppxai.config.execution"),
    ("ppxai.config.execution", "ppxai.engine.facts_resolver"),
    ("ppxai.engine.facts_resolver", "ppxai.engine.providers"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.facts_resolver"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.providers"),
    ("ppxai.common.consent", "ppxai.engine.tools.wrappers"),
    ("ppxai.config.execution", "ppxai.config.tools"),
    ("ppxai.config.execution", "ppxai.engine.model_facts"),
    ("ppxai.config.loader", "ppxai.config.tls"),
    ("ppxai.engine.providers.base", "ppxai.config.facts_config"),
    ("ppxai.engine.providers.gemini", "ppxai.usage"),
    ("ppxai.engine.providers.openai_compat", "ppxai.usage"),
    ("ppxai.engine.providers.openai_native", "ppxai.usage"),
    ("ppxai.engine.providers.perplexity", "ppxai.usage"),
    ("ppxai.engine.providers.wire.responses", "ppxai.usage"),
    ("ppxai.engine.task_authorizer", "ppxai.config.execution"),
    ("ppxai.engine.task_backend", "ppxai.config.execution"),
    ("ppxai.engine.tools.network_policy", "ppxai.config.execution"),
    ("ppxai.engine.tools.search_backends", "ppxai.config"),
    ("ppxai.rendering.rich_renderer", "ppxai.common.markdown_links"),
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"),
    ("ppxai.rendering.textual_renderer", "ppxai.common.markdown_links"),
    ("ppxai.server.auth", "ppxai.config.execution"),
    ("ppxai.server.http", "ppxai.config.loader"),
    ("ppxai.server.routes.agent_v1", "ppxai.config.execution"),
    ("ppxai.server.routes.config", "ppxai.config"),
    ("ppxai.server.routes.config", "ppxai.config.execution"),
    ("ppxai.server.routes.files", "ppxai.engine.tools.builtin.pptx_tools"),
    ("ppxai.server.routes.oneshot", "ppxai.server.routes.agent_v1"),
    ("ppxai.server.routes.sessions", "ppxai.config.execution"),
    ("ppxai.server.routes.sessions", "ppxai.server.auth"),
}


def _module_name(path):
    """Dotted name for a file under `ppxai/`, package-aware."""
    rel = path.relative_to(PPXAI.parent).with_suffix("")
    parts = list(rel.parts)
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def _package_of(module, is_init):
    """The package a relative import resolves against.

    For `__init__.py` the module IS its own package; for every other file
    the package is the parent. Getting this wrong produces phantom targets
    like `ppxai.commands.config.defaults`, which is how a first attempt at
    this analysis went astray — hence `test_every_target_resolves` below.
    """
    if is_init:
        return module
    return module.rsplit(".", 1)[0] if "." in module else module


def _resolve(node, module, is_init):
    """Absolute dotted target of an ImportFrom, or None for plain `import`."""
    level = node.level or 0
    if level == 0:
        return node.module
    base = _package_of(module, is_init).split(".")
    up = level - 1
    if up:
        base = base[:-up] if up <= len(base) else []
    return ".".join(base + ([node.module] if node.module else []))


def _guarded_by_import_error(fnnode, impnode):
    """True when the import sits under a `try:` handling ImportError."""
    for n in ast.walk(fnnode):
        if not isinstance(n, ast.Try):
            continue
        if impnode not in list(ast.walk(n)):
            continue
        for handler in n.handlers:
            names = []
            if isinstance(handler.type, ast.Name):
                names = [handler.type.id]
            elif isinstance(handler.type, ast.Tuple):
                names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
            if "ImportError" in names or "ModuleNotFoundError" in names:
                return True
    return False


def _sweep():
    """Every internal function-level import that is not exempt.

    Returns a list of `(module, target, lineno)`.
    """
    found = []
    for path in sorted(PPXAI.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        is_init = path.name == "__init__.py"
        module = _module_name(path)
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for imp in ast.walk(fn):
                if not isinstance(imp, (ast.Import, ast.ImportFrom)):
                    continue
                if isinstance(imp, ast.Import):
                    names = [a.name for a in imp.names]
                    if not any(n.startswith("ppxai") for n in names):
                        continue
                    target = names[0]
                else:
                    target = _resolve(imp, module, is_init)
                    if not (target and target.startswith("ppxai")):
                        continue
                # Exempt: optional-dependency guard.
                if _guarded_by_import_error(fn, imp):
                    continue
                # Exempt: a package __init__ importing its own submodules.
                if target == module or (is_init and target.startswith(module + ".")):
                    continue
                found.append((module, target, imp.lineno))
    return found


class TestTheSweepWorks:
    """Guards FIRST. Everything below is built on `_sweep()`, so a sweep that
    silently stops matching would make every other test here pass."""

    def test_the_sweep_finds_imports(self):
        assert _sweep(), (
            "the sweep found no function-level internal imports at all — it "
            "has stopped matching the code, not the code stopped violating"
        )

    def test_it_walks_a_realistic_number_of_files(self):
        files = list(PPXAI.rglob("*.py"))
        assert len(files) > 100, f"only {len(files)} files under ppxai/ — wrong root?"

    def test_every_target_resolves(self):
        """Relative-import resolution must produce real modules.

        A mis-resolved relative import yields a plausible-looking dotted name
        for a module that does not exist, and every downstream check then
        compares against fiction.
        """
        root = PPXAI.parent
        unresolved = []
        for module, target, line in _sweep():
            rel = target.replace(".", "/")
            if not (root / (rel + ".py")).exists() and not (root / rel / "__init__.py").exists():
                unresolved.append(f"{module}:{line} -> {target}")
        assert not unresolved, (
            "these targets do not name a real module, so the resolution is "
            "wrong rather than the code: " + "; ".join(unresolved)
        )


class TestNoNewLazyImports:
    def test_no_lazy_import_outside_the_baseline(self):
        current = {(m, t) for m, t, _ in _sweep()}
        added = sorted(current - BASELINE)
        assert not added, (
            "new internal lazy import(s). A function-level import of another "
            "ppxai module hides a dependency from the module graph — see "
            "docs/patterns/protocol-dependency-inversion.md (CRITICAL). Import "
            "at module scope; if that cycles, the dependency shape is wrong and "
            "a Protocol in a leaf module is the fix:\n  "
            + "\n  ".join(f"{m} -> {t}" for m, t in added)
        )

    def test_the_baseline_has_no_stale_rows(self):
        """A fixed import must be REMOVED from `BASELINE`.

        Otherwise the baseline drifts into a wish-list, and the diff stops
        being a record of what the cleanup actually did.
        """
        current = {(m, t) for m, t, _ in _sweep()}
        stale = sorted(BASELINE - current)
        assert not stale, (
            "these baseline rows no longer exist — delete them from BASELINE "
            "so it keeps describing the tree:\n  "
            + "\n  ".join(f"{m} -> {t}" for m, t in stale)
        )


class TestRetentionReasonsStayHonest:
    """`RETAINED_ON_PURPOSE` is a claim about the code, so test it as one.

    An annotation nobody checks rots into folklore: a row could be marked
    "cycle" long after the cycle is gone, and step 3 would skip it forever.
    """

    def test_every_retained_row_is_in_the_baseline(self):
        orphans = sorted(set(RETAINED_ON_PURPOSE) - BASELINE)
        assert not orphans, (
            "these rows are marked retained-on-purpose but are no longer in "
            "BASELINE — the import was fixed, so drop the annotation too:\n  "
            + "\n  ".join(f"{m} -> {t}" for m, t in orphans)
        )

    def test_every_baseline_row_has_a_reason(self):
        """Step 2 ended with every remaining row explained, so keep it that
        way: an unannotated row is one nobody can classify later."""
        unexplained = sorted(BASELINE - set(RETAINED_ON_PURPOSE))
        assert not unexplained, (
            "baseline rows with no retention reason — either hoist them or "
            "add a reason:\n  " + "\n  ".join(f"{m} -> {t}" for m, t in unexplained)
        )

    def test_the_reasons_are_from_the_known_set(self):
        allowed = {"cycle", "patch-semantics", "empty-block"}
        bad = {k: v for k, v in RETAINED_ON_PURPOSE.items() if v not in allowed}
        assert not bad, (
            f"unknown retention reason(s) {bad}. Add the category here "
            f"deliberately rather than inventing one at a call site."
        )

    def test_the_empty_block_row_really_is_a_sole_statement(self):
        """The one claim that is cheap to verify from source, so verify it —
        it is also the one most likely to become false, since any edit adding
        a second statement to that block silently invalidates the reason."""
        sole = [k for k, v in RETAINED_ON_PURPOSE.items() if v == "empty-block"]
        assert sole, "the empty-block category is documented but unused"
        for module, _target in sole:
            path = PPXAI.parent / (module.replace(".", "/") + ".py")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            singles = [
                n
                for n in ast.walk(tree)
                for field in ("body", "orelse", "finalbody")
                if isinstance(getattr(n, field, None), list)
                and len(getattr(n, field)) == 1
                and isinstance(getattr(n, field)[0], (ast.Import, ast.ImportFrom))
            ]
            assert singles, (
                f"{module} is marked empty-block, but no block in it has an "
                f"import as its only statement — the reason no longer holds"
            )


class TestTheBaselineIsShrinking:
    """The baseline is a debt ledger; pin its shape so it cannot quietly rot."""

    def test_the_baseline_is_not_empty_yet(self):
        """Fails once the cleanup finishes — at which point delete this test
        and the baseline, and the fence becomes a flat prohibition."""
        assert BASELINE, (
            "BASELINE is empty: every lazy import is gone. Delete BASELINE and "
            "TestTheBaselineIsShrinking, and assert `not _sweep()` outright."
        )

    @pytest.mark.parametrize("module,target", sorted(BASELINE))
    def test_each_baseline_row_names_a_real_module(self, module, target):
        root = PPXAI.parent
        for dotted in (module, target):
            rel = dotted.replace(".", "/")
            assert (root / (rel + ".py")).exists() or (root / rel / "__init__.py").exists(), (
                f"baseline row names {dotted}, which is not a module"
            )
