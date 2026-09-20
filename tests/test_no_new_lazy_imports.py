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
import json
import pathlib
import subprocess
import sys

import pytest

PPXAI = pathlib.Path(__file__).resolve().parent.parent / "ppxai"

#: Rows retained ON PURPOSE, with the reason. Everything in `BASELINE` that
#: is NOT here is simply "not hoisted yet" — step 2 work still to do.
#:
#: Without this split, step 3 inherits the whole baseline with no way to tell
#: "nobody got to it" from "moving this would break something", and the
#: obvious next action (hoist the rest) is wrong for these.
RETAINED_ON_PURPOSE = {
    # --- genuine import cycle (1) --------------------------------------
    # `loader -> tls -> store -> loader`, entirely inside `config`. A ring of
    # three needs ONE edge lazy; this is the narrowest (one call site, already
    # guarded). Measured: hoisting it re-closes the ring, and moving the cut
    # to `store -> loader` costs a row instead of saving one (Item 68 B).
    #
    # Was 8 at the start of step 3. The other seven were not what their rows
    # named — two expired tags, one fallback probe, and four that traced to a
    # package __init__ doing eager work rather than to the modules involved.
    ("ppxai.engine.facts_resolver", "ppxai.engine.providers"): "patch-semantics",
    ("ppxai.engine.task_authorizer", "ppxai.engine.facts_resolver"): "patch-semantics",
    ("ppxai.engine.task_authorizer", "ppxai.engine.providers"): "patch-semantics",
    ("ppxai.config.tls", "ppxai.config.store"): "cycle",
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
    # --- fallback probe (1) --------------------------------------------
    # Not a cycle: `tui/renderable/iterm2.py` imports stdlib + rich only and
    # loads standalone. It sits inside `_render_image_iterm2`, one of a family
    # of terminal-graphics probes whose sibling `_render_image_sixel` defers a
    # genuinely optional third-party import. In both, `except Exception:
    # return False` IS the fallback — each probe tries a protocol and reports
    # failure so the caller tries the next. Hoisting one breaks the family's
    # symmetry for no gain.
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"): "fallback-probe",
    # --- empty block (1) -----------------------------------------------
    # TWO sites share this pair, for two different reasons, and both must
    # stay lazy:
    #   handler.py:625  sole statement of its `try:` — deliberately
    #                   conditional (inline image preview, may be absent)
    #   handler.py:568  cuts the ring `rendering/__init__ -> base ->
    #                   commands/__init__ -> handler -> rich_renderer`.
    #                   Hoisting it is what makes `import ppxai.rendering`
    #                   fail standalone (Item 68 C).
    ("ppxai.commands.handler", "ppxai.rendering.rich_renderer"): "empty-block",
}

#: Internal function-level imports present when the fence was written,
#: measured at `12a2c9b7`. Every entry is a known violation awaiting steps
#: 2 and 3 — REMOVE rows as they are fixed; never add one.
BASELINE = {
    ("ppxai.commands.handler", "ppxai.rendering.rich_renderer"),
    ("ppxai.commands.doctor", "ppxai.config"),
    ("ppxai.commands.doctor", "ppxai.config.execution"),
    ("ppxai.engine.facts_resolver", "ppxai.engine.providers"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.facts_resolver"),
    ("ppxai.engine.task_authorizer", "ppxai.engine.providers"),
    ("ppxai.config.tls", "ppxai.config.store"),
    ("ppxai.config.execution", "ppxai.config.tools"),
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
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"),
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


class TestEveryPackageImportsStandalone:
    """Each top-level package must import on its own, in a fresh interpreter.

    `import ppxai.rendering` raised `ImportError: cannot import name
    'Renderer' from partially initialized module` for some time — the ring
    `rendering/__init__ -> base -> commands/__init__ -> handler ->
    rich_renderer -> base`. Nothing caught it because the app never imports
    `rendering` first; any new script or tool that did, broke.

    A fresh subprocess per package is the point: within one process an
    earlier import can prime `sys.modules` and hide the cycle entirely.
    """

    @pytest.mark.parametrize(
        "module",
        [
            "ppxai",
            "ppxai.commands",
            "ppxai.config",
            "ppxai.engine",
            "ppxai.rendering",
            "ppxai.server",
        ],
    )
    def test_the_package_imports_in_a_fresh_interpreter(self, module):
        proc = subprocess.run(
            [sys.executable, "-c", f"import {module}"],
            capture_output=True,
            text=True,
            timeout=120,
        )
        tail = (proc.stderr or "").strip().splitlines()
        detail = tail[-1] if tail else "(no stderr)"
        assert proc.returncode == 0, f"`import {module}` fails standalone: {detail}"


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
        allowed = {"cycle", "patch-semantics", "empty-block", "fallback-probe"}
        bad = {k: v for k, v in RETAINED_ON_PURPOSE.items() if v not in allowed}
        assert not bad, (
            f"unknown retention reason(s) {bad}. Add the category here "
            f"deliberately rather than inventing one at a call site."
        )

    def test_the_fallback_probe_row_still_sits_in_a_guard(self):
        """`fallback-probe` claims the import is inside a try/except that IS
        the fallback. Re-derive it: if someone removes the guard, the reason
        stops being true and the row should be reconsidered."""
        rows = [k for k, v in RETAINED_ON_PURPOSE.items() if v == "fallback-probe"]
        assert rows, "the fallback-probe category is documented but unused"
        for module, target in rows:
            path = PPXAI.parent / (module.replace(".", "/") + ".py")
            tree = ast.parse(path.read_text(encoding="utf-8"))
            guarded = False
            for node in ast.walk(tree):
                if not isinstance(node, ast.Try) or not node.handlers:
                    continue
                for imp in ast.walk(node):
                    if isinstance(imp, ast.ImportFrom) and target.endswith(
                        "." + (imp.module or "").rsplit(".", 1)[-1]
                    ):
                        guarded = True
            assert guarded, (
                f"{module} is marked fallback-probe, but its import of "
                f"{target} is no longer inside a try/except — the reason no "
                f"longer holds"
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


#: Modules known to fail a standalone import, with the debt item that owns
#: the fix. A row here is an EXEMPTION, not a pass: the test below asserts
#: each one still fails, so fixing the cycle turns the row into a failure
#: telling you to delete it. Never add a row to silence a NEW cycle -- that
#: is the regression this fence exists to catch.
KNOWN_IMPORT_CYCLES = {
    "ppxai.rendering.textual_renderer": (
        "debt Item 73 -- `rendering/textual_renderer.py:51` imports "
        "`..tui.widgets.dialog`, which runs `ppxai/tui/__init__.py`, which "
        "imports `tui.app`, which imports the renderer back while it is "
        "still initialising. Importing `tui.app` FIRST primes sys.modules "
        "and hides it, which is why the whole suite passes."
    ),
}

#: Body of the subprocess that does the sweep. Kept as a module constant so
#: the test reads as three assertions rather than a wall of nested source.
_SWEEP = r"""
import importlib, json, pathlib, sys

root = pathlib.Path(sys.argv[1])
mods = []
for f in sorted((root / "ppxai").rglob("*.py")):
    if {"graphify-out", "__pycache__", "tui"} & set(f.parts):
        continue
    parts = list(f.relative_to(root).with_suffix("").parts)
    if parts[-1] == "__init__":
        parts.pop()
    if parts:
        mods.append(".".join(parts))

fails = {}
for m in mods:
    # Purge only ppxai itself: third-party modules stay cached (that is what
    # makes this affordable), while every internal edge is rebuilt.
    for k in [k for k in sys.modules if k == "ppxai" or k.startswith("ppxai.")]:
        del sys.modules[k]
    try:
        importlib.import_module(m)
    except Exception as e:
        fails[m] = f"{type(e).__name__}: {e}"

print(json.dumps({"count": len(mods), "fails": fails}))
"""


class TestEveryModuleImportsStandalone:
    """Every module -- not just every package -- must import on its own.

    `TestEveryPackageImportsStandalone` above checks six package roots, and
    that is what let debt Item 73 through: `ppxai/rendering/__init__.py`
    does not pull `textual_renderer`, so the package imported clean while
    the module did not. The cycle surfaced only when something imported that
    module FIRST -- a new script, a tool, or one test file run on its own.

    Scope and method, both deliberate:

    * **`ppxai.tui.*` is excluded.** Importing it sets up the terminal and
      can hang -- the same reason this module's docstring already gives for
      verifying TUI modules through the suite instead. The Item 73 cycle is
      still caught, because the module that starts it lives in `rendering`.
    * **One subprocess with `sys.modules` purged between imports**, not a
      fresh interpreter per module. Per-module interpreters would be purer
      isolation at ~5s x 180; purging every `ppxai*` entry rebuilds the
      internal graph each time while third-party imports stay cached.
      Measured: ~30s for ~180 modules, and it finds the cycle the
      per-package test cannot.
    """

    def _failing_modules(self) -> dict[str, str]:
        """{module: error} for every module that fails to import alone."""
        proc = subprocess.run(
            [sys.executable, "-c", _SWEEP, str(PPXAI.parent)],
            capture_output=True,
            text=True,
            timeout=600,
        )
        assert proc.returncode == 0, (
            f"the sweep itself failed, so it proves nothing: {proc.stderr[-500:]}"
        )
        payload = json.loads(proc.stdout.strip().splitlines()[-1])
        assert payload["count"] > 150, (
            f"the sweep walked only {payload['count']} modules -- it is not "
            "finding the tree, and a green result would mean nothing"
        )
        return payload["fails"]

    def test_no_module_outside_the_known_cycles_fails_to_import(self):
        unexpected = {
            m: e
            for m, e in self._failing_modules().items()
            if m not in KNOWN_IMPORT_CYCLES
        }
        listing = "\n".join(f"  {m}\n      {e}" for m, e in sorted(unexpected.items()))
        assert not unexpected, (
            "these modules do not import standalone, which means an import "
            "cycle the app happens to hide by importing something else "
            f"first:\n{listing}\n\nFix the cycle. Do NOT add it to "
            "KNOWN_IMPORT_CYCLES -- that set is for the one pre-existing "
            "case, which has a debt item."
        )

    def test_every_known_cycle_is_still_broken(self):
        """A fixed cycle must lose its exemption, or the fence rots."""
        fixed = sorted(set(KNOWN_IMPORT_CYCLES) - set(self._failing_modules()))
        assert not fixed, (
            "these modules now import standalone, so the cycle is fixed -- "
            f"delete them from KNOWN_IMPORT_CYCLES: {fixed}"
        )


# ===========================================================================
# Guard 1 — `if TYPE_CHECKING:` is banned outright
# ===========================================================================
#
# `docs/patterns/protocol-dependency-inversion.md` rule 1 says "NEVER use
# `TYPE_CHECKING` — it's a lazy import in disguise", and this module's own
# docstring opens by quoting it. Nothing enforced it.
#
# The cost of that gap, measured: `ppxai/tui/session_restore_ops.py` imported
# `PPXAIDEApp` under `if TYPE_CHECKING:` from 2026-06 until 2026-09-20 — three
# months, inside the very layer the pattern doc governs, and it was the exact
# circular-import case the pattern exists to solve. It was found by a docs
# audit, not by the suite. A `SessionRestoreHost` Protocol replaced it.
#
# Why AST and not grep: the repo contains two legitimate *prose* mentions of
# the identifier (this file, and `providers/wire/protocol.py`'s docstring
# explaining why it is not needed). A grep fence would have to special-case
# them and would still miss `import typing; if typing.TYPE_CHECKING:`.


def _type_checking_hits(tree):
    """`(kind, lineno)` for every real use of TYPE_CHECKING in one tree.

    Two forms count, because either one reintroduces the hidden dependency:

    - `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` — the block itself.
    - `from typing import TYPE_CHECKING` — importing the name at all. There
      is no legitimate reason to bind it that does not end in the block
      above, and catching the import keeps the failure message pointing at
      the line a reader must delete.

    String mentions are invisible to this: a docstring is not an `If` node.
    """
    hits = []
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            name = None
            if isinstance(test, ast.Name):
                name = test.id
            elif isinstance(test, ast.Attribute):
                name = test.attr
            if name == "TYPE_CHECKING":
                hits.append(("if-block", node.lineno))
        elif isinstance(node, ast.ImportFrom):
            if any(a.name == "TYPE_CHECKING" for a in node.names):
                hits.append(("import", node.lineno))
    return hits


def _sweep_type_checking():
    """`(module, kind, lineno)` for every TYPE_CHECKING use under `ppxai/`."""
    found = []
    for path in sorted(PPXAI.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        for kind, lineno in _type_checking_hits(tree):
            found.append((_module_name(path), kind, lineno))
    return found


class TestTypeCheckingIsBanned:
    """Guards FIRST — a detector that stopped matching would pass silently."""

    def test_the_detector_sees_the_if_block_form(self):
        tree = ast.parse(
            "from typing import TYPE_CHECKING\n"
            "if TYPE_CHECKING:\n"
            "    from ppxai.tui.app import PPXAIDEApp\n"
        )
        kinds = {k for k, _ in _type_checking_hits(tree)}
        assert kinds == {"import", "if-block"}, kinds

    def test_the_detector_sees_the_attribute_form(self):
        """`import typing` + `typing.TYPE_CHECKING` is the same evasion."""
        tree = ast.parse("import typing\nif typing.TYPE_CHECKING:\n    import x\n")
        assert ("if-block", 2) in _type_checking_hits(tree)

    def test_the_detector_ignores_prose(self):
        """Docstrings and comments naming it must NOT trip the fence.

        Two files mention the identifier in prose on purpose — this module's
        docstring and `providers/wire/protocol.py`'s. A grep-based fence
        would have to carry an exclusion list for them; this one does not.
        """
        tree = ast.parse(
            '"""We never use TYPE_CHECKING here."""\n'
            "# if TYPE_CHECKING: would be wrong\n"
            "x = 'TYPE_CHECKING'\n"
        )
        assert _type_checking_hits(tree) == []

    def test_no_type_checking_anywhere_in_production_code(self):
        found = _sweep_type_checking()
        assert not found, (
            "`TYPE_CHECKING` is banned in production code — "
            "docs/patterns/protocol-dependency-inversion.md rule 1. It hides a "
            "dependency from the module graph exactly like a function-level "
            "import does, and the import it hides is almost always a cycle "
            "that wants a Protocol instead.\n\n"
            "Declare a structural `Protocol` in the leaf module that both "
            "sides already depend on (see `SessionRestoreHost` in "
            "ppxai/tui/session_restore_ops.py, or `ProtocolHandler` in "
            "ppxai/engine/providers/wire/protocol.py) and annotate against "
            "that:\n  "
            + "\n  ".join(f"{m}:{line} ({kind})" for m, kind, line in found)
        )


# ===========================================================================
# Guard 2 — `engine.completion` must stay a leaf of the engine package
# ===========================================================================
#
# ADR 0007. `ppxai/engine/completion.py:48` does
# `from ..commands.factory import CommandFactory` — the ONLY `engine ->
# commands` import in the whole engine package, and step 2 of that ADR (lift
# `complete()` into a `ppxai/completion/` package behind a Protocol) is still
# open after v1.19.0, .1 and .2.
#
# Measured 2026-09-20 while re-verifying the ADR: importing
# `ppxai.commands.factory` pulls **52** `ppxai.engine` modules. So the PACKAGE
# graph already cycles — engine -> commands -> engine.
#
# The MODULE graph does not, and that is the only reason nothing breaks:
# `engine.completion` is a leaf. `commands.factory` does not pull it, and no
# module inside `engine` imports it either, so the cycle is never closed at
# import time and `import ppxai.engine.completion` succeeds standalone.
#
# That leaf status is LOAD-BEARING AND UNDEFENDED. One `engine` module
# importing `engine.completion` — an obvious thing to do, since the name
# says it belongs to the engine — closes the loop and turns a dormant
# layering smell into an ImportError at startup. Nothing in the suite would
# have caught it. This is that check: one test, no refactor, and it can go
# away the day ADR 0007 step 2 lands and the upward import with it.


ENGINE_COMPLETION = "ppxai.engine.completion"


def _engine_modules_importing(target):
    """`(module, lineno)` for every module under `ppxai/engine/` importing
    `target` — at module scope or inside a function, both count.

    A function-level import closes the cycle just as hard; it only moves the
    moment it fires from startup to first call.
    """
    engine_root = PPXAI / "engine"
    found = []
    for path in sorted(engine_root.rglob("*.py")):
        module = _module_name(path)
        if module == target:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        is_init = path.name == "__init__.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                if any(a.name == target for a in node.names):
                    found.append((module, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                resolved = _resolve(node, module, is_init)
                if resolved == target:
                    found.append((module, node.lineno))
                elif resolved and any(
                    f"{resolved}.{a.name}" == target for a in node.names
                ):
                    found.append((module, node.lineno))
    return found


class TestEngineCompletionStaysALeaf:
    """Guards FIRST — see the module docstring's "the sweep must work" rule.

    **Mutation-verified 2026-09-20, and the two cases behave differently —
    which is the whole reason this guard is worth having.**

    Adding `from .completion import complete` at MODULE scope in
    `engine/client.py` does not fail this test. It fails the entire pytest
    run at collection, before any test executes::

        INTERNALERROR> ... ppxai/engine/client.py: from .completion import complete
        INTERNALERROR> ... ppxai/engine/completion.py:48: from ..commands.factory import CommandFactory
        INTERNALERROR> ... ppxai/commands/handler.py:29: from ..engine import EngineClient
        INTERNALERROR> ImportError: cannot import name 'EngineClient' from
                       partially initialized module 'ppxai.engine'
                       (most likely due to a circular import)

    That is loud, immediate, and needs no fence — but the traceback names
    `handler.py` and `EngineClient`, and says nothing about ADR 0007, so a
    reader can burn real time before finding the actual rule.

    The case that DOES need the fence is a **function-level** import inside
    an engine module. It defers the cycle to call time, so the package still
    imports, the suite still runs, every other test still passes, and the
    breakage surfaces only when that function is first called — possibly in
    a client, possibly in production. `_engine_modules_importing` walks the
    whole AST rather than just module scope for exactly that reason;
    mutating one in produces this test's failure and nothing else's.
    """

    def test_the_detector_resolves_a_relative_import(self):
        """`from .completion import complete` inside engine must be caught."""
        tree = ast.parse("from .completion import complete\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        assert _resolve(node, "ppxai.engine.client", False) == ENGINE_COMPLETION

    def test_the_detector_resolves_the_from_module_form(self):
        """`from . import completion` resolves to the package, not the name.

        This is the form the plain `_resolve` result misses, which is why the
        sweep also checks `f"{resolved}.{alias}"` — without that branch this
        guard would have a silent hole.
        """
        tree = ast.parse("from . import completion\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        resolved = _resolve(node, "ppxai.engine.client", False)
        assert resolved == "ppxai.engine"
        assert f"{resolved}.completion" == ENGINE_COMPLETION

    def test_the_engine_root_is_where_we_think(self):
        assert (PPXAI / "engine" / "completion.py").exists(), (
            "ppxai/engine/completion.py is gone — if ADR 0007 step 2 landed "
            "and it moved to ppxai/completion/, DELETE this whole guard "
            "class; it has done its job."
        )

    def test_no_engine_module_imports_engine_completion(self):
        offenders = _engine_modules_importing(ENGINE_COMPLETION)
        assert not offenders, (
            "a module under ppxai/engine/ now imports engine.completion, "
            "which closes the engine -> commands -> engine package cycle "
            "(ADR 0007).\n\n"
            "engine/completion.py:48 imports CommandFactory, and "
            "commands.factory pulls ~52 engine modules back. Today that is "
            "harmless ONLY because completion is a leaf nothing in engine "
            "reaches. Importing it from inside engine makes the cycle real.\n\n"
            "Call `complete()` from a client (rich/main.py, tui/completer.py, "
            "server/routes/completion.py all do), or land ADR 0007 step 2 and "
            "delete this guard:\n  "
            + "\n  ".join(f"{m}:{line}" for m, line in offenders)
        )
