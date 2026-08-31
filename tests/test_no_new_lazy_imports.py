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

**"Imports cleanly" is necessary but NOT sufficient.** A hoist can be
import-safe and still change behaviour, because it moves name resolution
from call time to import time:

    # lazy: resolved per call, so patch.object(tools, "get_tool_config") is seen
    def f():
        from .tools import get_tool_config

    # hoisted: this module binds its OWN reference at import time, and a
    # patch on the SOURCE module no longer reaches it

`config/execution.py` was reverted for exactly this — its lazy import sat
inside a `try:` whose docstring states "a capability must never survive the
failure of the config that governs it", and hoisting silently defeated both
that fail-safe and the test asserting it. 18 of the 89 import a name that
some test patches, so each batch needs its tests run, not just an import
check.
"""

import ast
import pathlib

import pytest

PPXAI = pathlib.Path(__file__).resolve().parent.parent / "ppxai"

#: Internal function-level imports present when the fence was written,
#: measured at `12a2c9b7`. Every entry is a known violation awaiting steps
#: 2 and 3 — REMOVE rows as they are fixed; never add one.
BASELINE = {
    ("ppxai.commands.agent", "ppxai.config.defaults"),
    ("ppxai.commands.attach", "ppxai.engine.artifact_projector"),
    ("ppxai.commands.attach", "ppxai.engine.model_facts"),
    ("ppxai.commands.attach", "ppxai.engine.multimodal_ops"),
    ("ppxai.commands.display", "ppxai.engine.tools.builtin.preview_log"),
    ("ppxai.commands.doctor", "ppxai.config"),
    ("ppxai.commands.doctor", "ppxai.config.execution"),
    ("ppxai.commands.doctor", "ppxai.config.facts_config"),
    ("ppxai.commands.doctor", "ppxai.config.tls"),
    ("ppxai.commands.doctor", "ppxai.engine.tools.search_backends"),
    ("ppxai.commands.handler", "ppxai.rendering.rich_renderer"),
    ("ppxai.commands.provider", "ppxai.config.facts_config"),
    ("ppxai.commands.provider", "ppxai.engine.model_facts"),
    ("ppxai.commands.provider", "ppxai.engine.providers"),
    ("ppxai.commands.system", "ppxai.commands.context"),
    ("ppxai.common.consent", "ppxai.engine.tools.wrappers"),
    ("ppxai.config.execution", "ppxai.config.tools"),
    ("ppxai.config.execution", "ppxai.engine.model_facts"),
    ("ppxai.config.loader", "ppxai.config.tls"),
    ("ppxai.engine.chat", "ppxai.config"),
    ("ppxai.engine.chat", "ppxai.config.defaults"),
    ("ppxai.engine.client", "ppxai.config"),
    ("ppxai.engine.client", "ppxai.engine.file_ref"),
    ("ppxai.engine.client", "ppxai.engine.tools.builtin.shell"),
    ("ppxai.engine.model_facts", "ppxai.config.facts_config"),
    ("ppxai.engine.model_facts", "ppxai.engine.providers"),
    ("ppxai.engine.model_facts", "ppxai.engine.providers.openai_compat"),
    ("ppxai.engine.multimodal_ops", "ppxai.engine.types"),
    ("ppxai.engine.multimodal_ops", "ppxai.engine.uploaded_file"),
    ("ppxai.engine.provider_ops", "ppxai.engine.model_facts"),
    ("ppxai.engine.providers.base", "ppxai.config.facts_config"),
    ("ppxai.engine.providers.gemini", "ppxai.usage"),
    ("ppxai.engine.providers.openai_compat", "ppxai.usage"),
    ("ppxai.engine.providers.openai_native", "ppxai.usage"),
    ("ppxai.engine.providers.perplexity", "ppxai.usage"),
    ("ppxai.engine.providers.wire.responses", "ppxai.usage"),
    ("ppxai.engine.session", "ppxai.engine.types"),
    ("ppxai.engine.task_authorizer", "ppxai.config.execution"),
    ("ppxai.engine.task_authorizer", "ppxai.config.loader"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.model_facts"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.providers"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.tools.search_backends"),
    ("ppxai.engine.task_backend", "ppxai.config.execution"),
    ("ppxai.engine.task_backend", "ppxai.engine.types"),
    ("ppxai.engine.task_runner", "ppxai.config.loader"),
    ("ppxai.engine.task_runner", "ppxai.engine.agent_runs"),
    ("ppxai.engine.tools.builtin.docx_tools", "ppxai.engine.file_ref"),
    ("ppxai.engine.tools.builtin.excel_tools", "ppxai.engine.file_ref"),
    ("ppxai.engine.tools.builtin.pdf_tools", "ppxai.engine.file_ref"),
    ("ppxai.engine.tools.builtin.pptx_tools", "ppxai.engine.file_ref"),
    ("ppxai.engine.tools.network_policy", "ppxai.config.execution"),
    ("ppxai.engine.tools.search_backends", "ppxai.config"),
    ("ppxai.engine.tools.wrappers.registry", "ppxai.config"),
    ("ppxai.engine.tools.wrappers.registry", "ppxai.engine.tools.wrappers.factory"),
    ("ppxai.engine.types", "ppxai.engine.artifact_projector"),
    ("ppxai.rendering.rich_renderer", "ppxai.common.markdown_links"),
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"),
    ("ppxai.rendering.textual_renderer", "ppxai.common.markdown_links"),
    ("ppxai.server.auth", "ppxai.config.execution"),
    ("ppxai.server.http", "ppxai.config.loader"),
    ("ppxai.server.http", "ppxai.server.state"),
    ("ppxai.server.routes.agent_v1", "ppxai.config.execution"),
    ("ppxai.server.routes.chat", "ppxai.commands.agent"),
    ("ppxai.server.routes.chat", "ppxai.config.defaults"),
    ("ppxai.server.routes.chat", "ppxai.engine.model_facts"),
    ("ppxai.server.routes.config", "ppxai.config"),
    ("ppxai.server.routes.config", "ppxai.config.execution"),
    ("ppxai.server.routes.files", "ppxai.common.docx_to_pdf"),
    ("ppxai.server.routes.files", "ppxai.engine.tools.builtin.docx_tools"),
    ("ppxai.server.routes.files", "ppxai.engine.tools.builtin.pptx_tools"),
    ("ppxai.server.routes.oneshot", "ppxai.engine"),
    ("ppxai.server.routes.oneshot", "ppxai.engine.task_authorizer"),
    ("ppxai.server.routes.oneshot", "ppxai.engine.tools.search_backends"),
    ("ppxai.server.routes.oneshot", "ppxai.server.routes.agent_v1"),
    ("ppxai.server.routes.oneshot", "ppxai.server.state"),
    ("ppxai.server.routes.sessions", "ppxai.config.execution"),
    ("ppxai.server.routes.sessions", "ppxai.engine.types"),
    ("ppxai.server.routes.sessions", "ppxai.server.auth"),
    ("ppxai.server.routes.sessions", "ppxai.server.routes.agent_v1"),
    ("ppxai.server.routes.sessions", "ppxai.server.state"),
    ("ppxai.server.routes.state", "ppxai.server.state"),
    ("ppxai.server.state", "ppxai.config.loader"),
    ("ppxai.server.state", "ppxai.engine.task_runner"),
    ("ppxai.server.state", "ppxai.server.secrets"),
    ("ppxai.tui", "ppxai.config"),
    ("ppxai.tui.app", "ppxai.config"),
    ("ppxai.tui.app", "ppxai.engine.task_backend"),
    ("ppxai.tui.app", "ppxai.tui.run_consent"),
    ("ppxai.tui.app", "ppxai.tui.session_restore_ops"),
    ("ppxai.tui.run_consent", "ppxai.tui.screens.consent"),
    ("ppxai.tui.widgets.image_handlers", "ppxai.tui.widgets.iterm2_widget"),
    ("ppxai.tui.widgets.message_box", "ppxai.engine.artifact_projector"),
    ("ppxai.tui.widgets.message_box", "ppxai.engine.types"),
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
