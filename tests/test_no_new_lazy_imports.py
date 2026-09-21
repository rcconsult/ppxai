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
    ("ppxai.config.tls", "ppxai.config.store"): "cycle",
    # --- patch semantics (25) ------------------------------------------
    # Hoisting binds the name at import time, so a test patching it on the
    # source module stops reaching it. Grep the imported name in tests/ to
    # see which test.
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
    ("ppxai.config.tls", "ppxai.config.store"),
    ("ppxai.rendering.rich_renderer", "ppxai.tui.renderable.iterm2"),
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
# Guard 2 — `ppxai/engine/` must not import `ppxai.commands`
# ===========================================================================
#
# ADR 0007, step 4 (2026-09-21). This guard REPLACES
# `TestEngineCompletionStaysALeaf`, which fenced the single symptom:
# `engine/completion.py` reached UP into the command layer
# (`from ..commands.factory import CommandFactory`) to read the command
# roster, and that edge made the PACKAGE graph cycle — importing
# `ppxai.commands.factory` pulls ~52 `ppxai.engine` modules back, so the
# direction of travel was engine -> commands -> engine. The MODULE graph
# stayed acyclic for one reason only: nothing inside `engine` imported
# `engine.completion`, so the loop was never closed at import time. That
# leaf status was load-bearing and undefended, which is what the old guard
# defended — an interim measure whose own failure message said to delete it
# the day the upward import went away.
#
# Step 4 removed the import instead of the symptom: the three CALLERS
# (`rich/main.py`, `tui/completer.py`, `server/routes/completion.py`) each
# read `CommandFactory.roster(<their client>)["commands"]` and hand
# `complete()` that plain data. So there is nothing left to be a leaf ABOUT,
# and the right fence is the layering rule itself, held at zero:
#
#     the engine does not know the command layer exists.
#
# Same shape and same reasoning as Guard 3 (`config` must not import
# `engine`): a rule at zero, walking the WHOLE AST so a function-level
# evasion counts, with the guards tested before the sweep.


def _engine_to_commands_edges():
    """`(module, target, lineno)` for every `engine -> commands` import.

    Module scope AND function level, across the whole `ppxai/engine/`
    package. A function-level import closes the cycle just as hard; it only
    moves the moment it fires from startup to first call.
    """
    found = []
    engine_root = PPXAI / "engine"
    for path in sorted(engine_root.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        module = _module_name(path)
        is_init = path.name == "__init__.py"
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name == "ppxai.commands" or a.name.startswith(
                        "ppxai.commands."
                    ):
                        found.append((module, a.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = _resolve(node, module, is_init)
                if target and (target == "ppxai.commands"
                               or target.startswith("ppxai.commands.")):
                    found.append((module, target, node.lineno))
                elif target == "ppxai":
                    for a in node.names:
                        if a.name == "commands":
                            found.append((module, "ppxai.commands", node.lineno))
    return found


class TestEngineImportsNoCommands:
    """Guards FIRST — a detector that stopped matching would pass forever.

    **Mutation-verified 2026-09-21, and the result differs from Guard 3's —
    which makes this fence MORE load-bearing, not less.**

    For Guard 3 (`config -> engine`) and for the retired
    `TestEngineCompletionStaysALeaf` (`engine -> engine.completion`), a
    module-scope mutation was LOUD: it took the whole pytest run down at
    collection with a partially-initialized-module `ImportError`, so the
    fence only really bought the function-level case.

    Not here. Both mutations were re-run on 2026-09-21:

    - **Module scope** — `from ..commands.factory import CommandFactory`
      restored at the top of `engine/completion.py` (literally the line ADR
      0007 step 4 deleted): **`pytest --collect-only` collects all 6,285
      tests, `import ppxai.engine.completion` succeeds in a fresh
      interpreter, and the completion suites stay green.** NOTHING fails
      except this test. The cycle is real (`commands.factory` pulls ~52
      `ppxai.engine` modules) but stays dormant, because `engine.completion`
      is a leaf no engine module imports — which is exactly the silent state
      this edge sat in for three releases.
    - **Function level** — the same import inside a function in
      `engine/completion.py`: this test fails, and so does
      `TestNoNewLazyImports` (a function-level internal import breaks that
      rule too). Nothing else fails.

    So the whole `engine -> commands` rule is silent in production and needs
    a test to be visible at all. `_engine_to_commands_edges` walks the whole
    AST, module scope and function bodies alike, for that reason.
    """

    def test_the_detector_resolves_a_relative_import(self):
        """`from ..commands.factory import CommandFactory` must be caught."""
        tree = ast.parse("from ..commands.factory import CommandFactory\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        assert _resolve(node, "ppxai.engine.completion", False) == (
            "ppxai.commands.factory"
        )

    def test_the_detector_resolves_the_from_package_form(self):
        """`from .. import commands` names the package, not a submodule.

        This is the form a plain `_resolve` result misses — it returns
        `ppxai` — which is why the sweep also inspects the imported NAMES.
        Without that branch this guard would have a silent hole.
        """
        tree = ast.parse("from .. import commands\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        assert _resolve(node, "ppxai.engine.completion", False) == "ppxai"
        assert [a.name for a in node.names] == ["commands"]

    def test_the_detector_sees_an_absolute_import(self):
        tree = ast.parse("import ppxai.commands.factory\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.Import))
        assert node.names[0].name.startswith("ppxai.commands")

    def test_the_engine_and_commands_packages_are_where_we_think(self):
        assert (PPXAI / "engine").is_dir(), "wrong root?"
        assert (PPXAI / "commands" / "factory.py").exists(), "wrong root?"

    def test_the_engine_imports_nothing_from_commands(self):
        edges = _engine_to_commands_edges()
        assert not edges, (
            "a module under ppxai/engine/ imports ppxai/commands/, which "
            "inverts the layering and makes the two packages mutually "
            "dependent (ADR 0007).\n\n"
            "The layers are Engine -> Server -> Clients, and `commands` sits "
            "ABOVE the engine: importing `ppxai.commands.factory` pulls ~52 "
            "`ppxai.engine` modules back, so this edge closes an "
            "engine -> commands -> engine package cycle. It held at zero "
            "from 2026-09-21, when ADR 0007 step 4 removed the last one "
            "(`engine/completion.py` reading the command roster).\n\n"
            "If the engine needs command DATA, the CALLER passes it in as "
            "plain data — that is what `complete(roster=...)` does: "
            "`rich/main.py`, `tui/completer.py` and "
            "`server/routes/completion.py` each read "
            "`CommandFactory.roster(<their client>)[\"commands\"]` and hand it "
            "over. Do not add a `roster=None` fallback that imports the "
            "factory; that is this edge again, behind a branch:\n  "
            + "\n  ".join(f"{m}:{line} -> {t}" for m, t, line in edges)
        )


# ===========================================================================
# Guard 3 — `config/` must not import `engine/`
# ===========================================================================
#
# The layering intent is that `config` READS settings and `engine` CONSUMES
# them, so the dependency points one way: engine -> config. It did not.
# `config/facts_config.py` imported `engine.model_facts` and `engine.types`
# at module scope, which made the two packages mutually dependent and
# produced a zigzag nobody could read off the imports:
#
#     engine.facts_resolver -> config.facts_config -> engine.model_facts
#
# It never deadlocked, because `model_facts` and `types` are leaves that
# import no config — so the MODULE graph stayed acyclic while the PACKAGE
# graph did not. That is the same undefended-leaf shape as ADR 0007's
# `engine.completion`, and it is why this is a test and not a comment.
#
# Fixed 2026-09-20 by moving the module to `ppxai/engine/facts_config.py`,
# where it sits beside the `model_facts` it resolves and the
# `facts_resolver` that calls it. It keeps ONE outward edge —
# `config.loader` for raw JSON reading — which is fine and one-way:
# `config/loader.py` imports no engine.
#
# Those two import statements were the ONLY `config -> engine` edges in the
# whole package, so after the move `config/` is engine-free and this guard
# holds the line at zero rather than at a baseline.


def _config_to_engine_edges():
    """`(module, target, lineno)` for every `config -> engine` import."""
    found = []
    cfg = PPXAI / "config"
    for path in sorted(cfg.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        module = _module_name(path)
        is_init = path.name == "__init__.py"
        for node in ast.walk(tree):          # module scope AND function level
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name.startswith("ppxai.engine"):
                        found.append((module, a.name, node.lineno))
            elif isinstance(node, ast.ImportFrom):
                target = _resolve(node, module, is_init)
                if target and (target == "ppxai.engine"
                               or target.startswith("ppxai.engine.")):
                    found.append((module, target, node.lineno))
    return found


class TestConfigDoesNotImportEngine:
    """Guards FIRST — a detector that stops matching would pass forever.

    **Mutation-verified 2026-09-20, and as with Guard 2 (engine -> commands)
    the two cases behave differently — which is why this test exists.**

    A MODULE-scope `from ..engine.types import X` in `config/loader.py` does
    not fail this test. It kills the whole pytest run at collection::

        INTERNALERROR> ppxai/config/loader.py: from ..engine.types import ...
        INTERNALERROR> ppxai/engine/__init__.py:14: from .client import EngineClient
        INTERNALERROR> ppxai/engine/client.py:15: from ..checkpoint import CheckpointManager
        INTERNALERROR> ppxai/checkpoint.py:25: from .config import SESSIONS_DIR
        INTERNALERROR> ImportError: cannot import name 'SESSIONS_DIR' from
                       partially initialized module 'ppxai.config'

    That is loud — and it is also proof the layering is load-bearing rather
    than tidy: `config -> engine -> checkpoint -> config` closes immediately.

    The case that NEEDS the fence is a FUNCTION-level import, which defers
    the cycle to call time: the package imports, the suite runs green, and
    the breakage waits for whenever that function is first called. That is
    precisely how `config/facts_config.py` survived — its edges were at
    module scope but onto LEAVES (`model_facts`, `types`), so nothing ever
    closed the loop and nothing complained. `_config_to_engine_edges` walks
    the whole AST for that reason; mutating a lazy one in fails this test
    and nothing else.
    """

    def test_the_detector_resolves_a_relative_engine_import(self):
        """`from ..engine.model_facts import X` inside config must be caught."""
        tree = ast.parse("from ..engine.model_facts import ModelFacts\n")
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.ImportFrom))
        assert _resolve(node, "ppxai.config.facts_config", False) == "ppxai.engine.model_facts"

    def test_the_config_package_is_where_we_think(self):
        assert (PPXAI / "config" / "loader.py").exists(), "wrong root?"

    def test_config_imports_nothing_from_engine(self):
        edges = _config_to_engine_edges()
        assert not edges, (
            "a module under ppxai/config/ now imports ppxai/engine/, which "
            "makes the two packages mutually dependent.\n\n"
            "`config` reads settings; `engine` consumes them. The edge points "
            "engine -> config, never back. This held at zero from 2026-09-20, "
            "when engine/facts_config.py moved out of config/ — it was the "
            "last such edge.\n\n"
            "If you need an engine DATA TYPE in config, that is the signal "
            "that the code using it belongs in engine/ instead (which is "
            "exactly what facts_config turned out to be — resolution logic, "
            "not configuration):\n  "
            + "\n  ".join(f"{m}:{line} -> {t}" for m, t, line in edges)
        )


# ===========================================================================
# Guard 4 — tests/ must not GAIN new function-level `ppxai` imports
# ===========================================================================
#
# Owner decision 2026-09-21. The three guards above hold `ppxai/` production
# code at a baseline (or at zero); nothing did the same for `tests/`. In this
# very session, sub-agents added nested `ppxai` imports to brand-new test
# files three times despite being told not to, because nothing failed. This
# fence closes that hole the same way Guard 0 (`TestNoNewLazyImports`) closes
# it for `ppxai/` — a per-file baseline that can shrink but never grow.
#
# **Per-FILE counts, not per-(module, target) pairs.** The `ppxai/` baseline
# above pins exactly which edge exists, because steps 2/3 fix them one at a
# time and the pair is the unit of that work. Nobody is about to hoist 1,258
# rows in `tests/` — see the module docstring addendum below — so the unit
# that matters here is simpler: does THIS FILE'S count of function-level
# `ppxai` imports go up. A per-file count catches the failure mode that
# actually happened this session (a NEW file appearing with a nested import,
# or an existing file picking up an extra one) without pretending to track
# which specific import moved.
#
# **Deliberate deferred imports are common and legitimate here** — a test
# importing `ppxai.x` AFTER `monkeypatch.setenv(...)` or after patching a
# module attribute so module-level state resolves under the patch. Hoisting
# those is explicitly NOT this task (and would break the patched tests, the
# same trap `RETAINED_ON_PURPOSE` above documents for `ppxai/`). The baseline
# below is a debt/inventory snapshot, not a to-do list to clear.
#
# **Scope: every `.py` under `tests/`, no exclusions.** `conftest.py` files
# and `tests/e2e/` are included — a conftest fixture or an e2e helper is as
# capable of hiding a dependency as a `test_*.py` file, and carving out an
# exception is exactly the kind of hole this fence exists to not have.
#
# **Baseline keys are repo-root-relative (`"tests/test_tui.py"`), not
# tests-relative** — matching how files are named everywhere else in this
# project (commit messages, CLAUDE.md, `pytest tests/...`).


TESTS_ROOT = pathlib.Path(__file__).resolve().parent
REPO_ROOT = TESTS_ROOT.parent


def _try_handles_import_error(trynode):
    """True when a `Try` node's `except` clause(s) name `ImportError` or
    `ModuleNotFoundError` — the same test `_guarded_by_import_error` makes
    above, factored out so it can be checked once per `Try` node instead of
    once per import candidate (see the perf note on `_function_level_ppxai_imports`).
    """
    for handler in trynode.handlers:
        names = []
        if isinstance(handler.type, ast.Name):
            names = [handler.type.id]
        elif isinstance(handler.type, ast.Tuple):
            names = [e.id for e in handler.type.elts if isinstance(e, ast.Name)]
        if "ImportError" in names or "ModuleNotFoundError" in names:
            return True
    return False


def _function_level_ppxai_imports(tree, module, is_init):
    """`(target, lineno)` for every non-exempt function-level `ppxai` import
    in one already-parsed tree.

    A single-tree extractor (not a directory walker) so the exact same
    function backs both the full `tests/` sweep and the synthetic-source
    self-tests below — no second implementation to drift out of sync.

    Correctness note this function exists to get right: counting must not
    double-count a NESTED `def`. The obvious `for fn in ast.walk(tree): if
    isinstance(fn, FunctionDef): ...` idiom (used by `_sweep()` above, for
    `ppxai/`, where it is harmless because nothing there nests defs three
    deep around an import) walks into an inner function from BOTH the outer
    function's subtree AND the inner function's own top-level iteration,
    counting one import twice. A depth-tracking visitor counts it once,
    however deeply nested, because it visits each AST node exactly once.

    Perf note: the ImportError-guard exemption is tracked the same way, with
    a `guard_depth` counter bumped on entering a guarding `Try` node, rather
    than re-walking the whole tree per import candidate to ask "am I inside
    one". The re-walk version was measured at 7.2s on `tests/test_tui.py`
    alone (quadratic: tree size x import count); this version is linear —
    the whole `tests/` sweep drops from ~14s to well under 1s.
    """

    class _Finder(ast.NodeVisitor):
        def __init__(self):
            self.depth = 0
            self.guard_depth = 0
            self.hits = []

        def visit_FunctionDef(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        def visit_AsyncFunctionDef(self, node):
            self.depth += 1
            self.generic_visit(node)
            self.depth -= 1

        def visit_Try(self, node):
            guarded = _try_handles_import_error(node)
            if guarded:
                self.guard_depth += 1
            self.generic_visit(node)
            if guarded:
                self.guard_depth -= 1

        def visit_Import(self, node):
            if self.depth > 0 and self.guard_depth == 0:
                self._maybe_record(node)
            self.generic_visit(node)

        def visit_ImportFrom(self, node):
            if self.depth > 0 and self.guard_depth == 0:
                self._maybe_record(node)
            self.generic_visit(node)

        def _maybe_record(self, node):
            if isinstance(node, ast.Import):
                ppxai_names = [a.name for a in node.names if a.name.startswith("ppxai")]
                if not ppxai_names:
                    return
                target = ppxai_names[0]
            else:
                target = _resolve(node, module, is_init)
                if not (target and target.startswith("ppxai")):
                    return
            self.hits.append((target, node.lineno))

    finder = _Finder()
    finder.visit(tree)
    return finder.hits


def _tests_dir_import_counts():
    """`{"tests/relative/path.py": count}` — live from disk, current tree."""
    counts = {}
    for path in sorted(TESTS_ROOT.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except SyntaxError:
            continue
        is_init = path.name == "__init__.py"
        module = _module_name(path)
        hits = _function_level_ppxai_imports(tree, module, is_init)
        if hits:
            rel = str(path.relative_to(REPO_ROOT))
            counts[rel] = len(hits)
    return counts


class TestTheTestsDirExtractorWorks:
    """Guards FIRST, same discipline as `TestTheSweepWorks` above — every
    other test in this section is built on `_function_level_ppxai_imports`
    and `_tests_dir_import_counts`, so a detector that silently stopped
    matching would make the fence below pass for the wrong reason."""

    def test_module_level_import_not_counted(self):
        tree = ast.parse("import ppxai.x\n")
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_module_level_if_import_not_counted(self):
        """A module-scope `if` is not a function — depth stays 0."""
        tree = ast.parse("if True:\n    import ppxai.x\n")
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_import_inside_def_counted_once(self):
        tree = ast.parse("def f():\n    import ppxai.x\n")
        assert len(_function_level_ppxai_imports(tree, "tests.fake", False)) == 1

    def test_import_inside_async_def_counted_once(self):
        tree = ast.parse("async def f():\n    import ppxai.x\n")
        assert len(_function_level_ppxai_imports(tree, "tests.fake", False)) == 1

    def test_import_inside_method_counted_once(self):
        tree = ast.parse("class C:\n    def m(self):\n        import ppxai.x\n")
        assert len(_function_level_ppxai_imports(tree, "tests.fake", False)) == 1

    def test_nested_def_counted_once(self):
        """The double-count trap this extractor was written to avoid: an
        import inside a def nested inside another def must be ONE hit, not
        two (once for the outer function's subtree walk, once for the
        inner function's own top-level iteration)."""
        tree = ast.parse(
            "def outer():\n    def inner():\n        import ppxai.x\n    return inner\n"
        )
        assert len(_function_level_ppxai_imports(tree, "tests.fake", False)) == 1

    def test_absolute_plain_import_counted(self):
        tree = ast.parse("def f():\n    import ppxai.x\n")
        hits = _function_level_ppxai_imports(tree, "tests.fake", False)
        assert hits == [("ppxai.x", 2)]

    def test_absolute_from_import_counted(self):
        tree = ast.parse("def f():\n    from ppxai.x import y\n")
        hits = _function_level_ppxai_imports(tree, "tests.fake", False)
        assert hits == [("ppxai.x", 2)]

    def test_relative_from_import_counted(self):
        """`from . import z`. Real files under `tests/` cannot structurally
        produce a relative import that resolves onto `ppxai` — `tests/` and
        `ppxai/` are siblings, not nested packages — so this exercises the
        resolver mechanism with a deliberately contrived module context
        (`_resolve` is shared with the `ppxai/` guards above and is already
        proven correct there); it is defense in depth, not a realistic case.
        `_resolve` names the PACKAGE here (`"ppxai"`, not `"ppxai.z"`) for a
        `from . import z` form with no `node.module` — the same behaviour
        Guard 2's `test_the_detector_resolves_the_from_package_form` already
        pins for this helper; it still starts with `"ppxai"`, so it counts.
        """
        tree = ast.parse("def f():\n    from . import z\n")
        hits = _function_level_ppxai_imports(tree, "ppxai.fake", False)
        assert hits == [("ppxai", 2)]

    def test_relative_dotted_from_import_counted(self):
        """`from ..a import b`, same contrived-context rationale as above."""
        tree = ast.parse("def f():\n    from ..a import b\n")
        hits = _function_level_ppxai_imports(tree, "ppxai.sub.fake", False)
        assert hits == [("ppxai.a", 2)]

    def test_stdlib_nested_import_not_counted(self):
        tree = ast.parse("def f():\n    import os\n    from collections import OrderedDict\n")
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_third_party_nested_import_not_counted(self):
        tree = ast.parse("def f():\n    import pytest\n")
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_string_mention_not_counted(self):
        """A string that merely CONTAINS import-like text must not trip the
        AST-based extractor — only real `Import`/`ImportFrom` nodes count."""
        tree = ast.parse('def f():\n    x = "from ppxai import y"\n    return x\n')
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_positive_control_a_planted_violation_is_detected(self):
        """If the extractor cannot see an obvious violation, nothing below
        it can be trusted."""
        tree = ast.parse("def test_something():\n    import ppxai.version\n")
        hits = _function_level_ppxai_imports(tree, "tests.test_planted", False)
        assert hits == [("ppxai.version", 2)]

    def test_import_error_guarded_import_not_counted(self):
        """Same optional-dependency exemption `_guarded_by_import_error`
        gives the `ppxai/` fence above — deferring inside a guarded `try` is
        the point of an optional import, in tests/ as much as in ppxai/."""
        tree = ast.parse(
            "def f():\n"
            "    try:\n"
            "        import ppxai.optional_thing\n"
            "    except ImportError:\n"
            "        pass\n"
        )
        assert _function_level_ppxai_imports(tree, "tests.fake", False) == []

    def test_the_tests_dir_is_where_we_think(self):
        assert (TESTS_ROOT / "test_no_new_lazy_imports.py").exists(), "wrong root?"
        assert (REPO_ROOT / "ppxai").is_dir(), "wrong root?"

    def test_it_walks_a_realistic_number_of_files(self):
        """A corpus-size floor, so a broken glob (wrong root, wrong suffix,
        an early `return`) reads as "nothing to see" instead of green."""
        files = list(TESTS_ROOT.rglob("*.py"))
        assert len(files) >= 200, f"only {len(files)} files under tests/ — wrong root?"


#: Per-file count of function-level `ppxai` imports under `tests/`, keyed by
#: repo-root-relative path. Generated mechanically from `_tests_dir_import_counts()`
#: — see the class docstring below for the exact procedure — then pasted in as
#: a literal, the same choice `BASELINE` above makes for the same reason: a
#: ~130-row dict is still more legible, greppable and diff-reviewable as a
#: sorted literal than as a JSON sidecar nobody reads without a text editor.
#:
#: A file NOT in this dict is allowed ZERO function-level `ppxai` imports.
#: Measured 2026-09-21 at HEAD `9d8c5764` (see `TestTheTestsDirBaselineIsHonest`
#: for how in-flight concurrent edits were handled).
BASELINE_TESTS_DIR = {
    "tests/conftest.py": 5,
    "tests/test_adr0012_migration_fence.py": 14,
    "tests/test_agent_beat_cross_client_parity.py": 3,
    "tests/test_agent_beat_emission.py": 7,
    "tests/test_agent_beat_textual_renderer.py": 2,
    "tests/test_agent_beat_zombie.py": 6,
    "tests/test_agent_logger_attribute.py": 7,
    "tests/test_agent_run_authz.py": 1,
    "tests/test_agent_runs.py": 103,
    "tests/test_agent_scoped_tools.py": 11,
    "tests/test_agent_spawn.py": 9,
    "tests/test_agent_spec.py": 1,
    "tests/test_agent_system_prompt.py": 5,
    "tests/test_agent_task_validation.py": 1,
    "tests/test_app_state.py": 1,
    "tests/test_attach_command.py": 4,
    "tests/test_attach_remove.py": 2,
    "tests/test_attach_vision_warning.py": 6,
    "tests/test_auth_middleware.py": 17,
    "tests/test_auto_command_cross_client.py": 1,
    "tests/test_background_agents_mirror.py": 1,
    "tests/test_benchmark_runner.py": 2,
    "tests/test_bootstrap_context.py": 14,
    "tests/test_capability_resolution.py": 11,
    "tests/test_chat_route_r15.py": 1,
    "tests/test_collect_semantics.py": 16,
    "tests/test_command_envelope.py": 4,
    "tests/test_command_result_serialization.py": 2,
    "tests/test_commands.py": 3,
    "tests/test_completion_provider.py": 3,
    "tests/test_config.py": 19,
    "tests/test_config_facts_are_complete.py": 1,
    "tests/test_context_attachments_state.py": 2,
    "tests/test_context_injection.py": 1,
    "tests/test_context_percentage_state.py": 11,
    "tests/test_csv_tools.py": 13,
    "tests/test_custom_endpoint_integration.py": 14,
    "tests/test_cwd_grounding.py": 4,
    "tests/test_data.py": 25,
    "tests/test_directory_result_renderers.py": 4,
    "tests/test_display_edit_handler.py": 1,
    "tests/test_docs_consistency.py": 3,
    "tests/test_doctor.py": 12,
    "tests/test_doctor_uncatalogued.py": 1,
    "tests/test_engine_client_protocol.py": 4,
    "tests/test_engine_streaming.py": 11,
    "tests/test_engine_tool_parsing.py": 27,
    "tests/test_event_bus.py": 2,
    "tests/test_excel_pptx_tools.py": 4,
    "tests/test_execution_profiles.py": 23,
    "tests/test_facts_doctor.py": 8,
    "tests/test_facts_resolver.py": 1,
    "tests/test_file_editing_tools.py": 27,
    "tests/test_file_tree.py": 24,
    "tests/test_file_tree_ignore_config.py": 15,
    "tests/test_files_cwd_anchor.py": 1,
    "tests/test_files_preview_download.py": 8,
    "tests/test_files_route.py": 6,
    "tests/test_files_upload.py": 1,
    "tests/test_gemini_native_tool_loop.py": 2,
    "tests/test_gemini_null_parts.py": 2,
    "tests/test_gemini_thought_signature.py": 1,
    "tests/test_gemini_tool_schema.py": 2,
    "tests/test_handle_save.py": 1,
    "tests/test_http_server.py": 5,
    "tests/test_image_handlers.py": 3,
    "tests/test_image_session_query.py": 1,
    "tests/test_markdown_tables.py": 12,
    "tests/test_model_facts_are_the_source.py": 2,
    "tests/test_model_vision.py": 2,
    "tests/test_network_policy.py": 10,
    "tests/test_oneshot_grounding.py": 19,
    "tests/test_oneshot_route.py": 20,
    "tests/test_openai_native.py": 2,
    "tests/test_ops_modules.py": 1,
    "tests/test_pdf_tools.py": 1,
    "tests/test_per_model_capabilities.py": 2,
    "tests/test_perplexity_capability_probe.py": 2,
    "tests/test_perplexity_model_capabilities.py": 8,
    "tests/test_pptx_render.py": 18,
    "tests/test_premium_web_search_integration.py": 13,
    "tests/test_preview.py": 53,
    "tests/test_preview_log_tool.py": 5,
    "tests/test_prompt_text_side_effect.py": 1,
    "tests/test_pyinstaller_spec_completeness.py": 1,
    "tests/test_r19_ppxaide_multimodal.py": 17,
    "tests/test_r5_end_to_end.py": 1,
    "tests/test_r5_provider_flatten.py": 7,
    "tests/test_r5_session_round_trip.py": 1,
    "tests/test_reasoning_tokens.py": 11,
    "tests/test_recommended_defaults_have_facts.py": 2,
    "tests/test_rest_event_piggyback.py": 1,
    "tests/test_rich_markdown_link_rewrite.py": 1,
    "tests/test_schema_endpoint.py": 2,
    "tests/test_search_backend_resolver.py": 7,
    "tests/test_server_route_edges.py": 1,
    "tests/test_server_routes.py": 3,
    "tests/test_session_persistence.py": 30,
    "tests/test_session_security.py": 1,
    "tests/test_session_store_engine_integration.py": 1,
    "tests/test_shell_tool.py": 2,
    "tests/test_shipped_model_facts.py": 7,
    "tests/test_stream_handler_dispatch.py": 2,
    "tests/test_task_authorization_parity.py": 14,
    "tests/test_task_backend.py": 3,
    "tests/test_task_command.py": 4,
    "tests/test_task_grammar_parity.py": 1,
    "tests/test_terminal_pty.py": 8,
    "tests/test_tls_config.py": 1,
    "tests/test_tokens_v1_route.py": 3,
    "tests/test_tool_messages.py": 3,
    "tests/test_tool_security.py": 4,
    "tests/test_tool_usage.py": 6,
    "tests/test_tui.py": 289,
    "tests/test_tui_command_factory.py": 7,
    "tests/test_ui.py": 7,
    "tests/test_undefined_names_are_bound.py": 3,
    "tests/test_usage_integration.py": 8,
    "tests/test_usage_persistence.py": 2,
    "tests/test_v18_1_audited_commands.py": 2,
    "tests/test_v1_session_migration.py": 2,
    "tests/test_version_banner.py": 7,
    "tests/test_vision_sidecar.py": 12,
    "tests/test_web_premium_wire.py": 4,
    "tests/test_web_search_task_config.py": 13,
    "tests/test_web_tools_ssl.py": 2,
    "tests/test_wire_block_validator.py": 1,
    "tests/test_wire_handlers_complete.py": 1,
    "tests/test_word_preview.py": 10,
    "tests/test_wrapper_framework.py": 6,
}


class TestNoNewLazyImportsInTestsDir:
    """The fence itself: a file's count may fall, may hold, may not rise.

    **Baseline generation procedure** (re-run to regenerate `BASELINE_TESTS_DIR`):
    for every `.py` under `tests/`, count via `_tests_dir_import_counts()`.
    For a file `git status --porcelain` shows as modified or untracked at
    generation time, use the count from `git show HEAD:<path>` instead of the
    working-tree count (0 for a file untracked at HEAD) — NOT because the
    working-tree edit is assumed wrong, but because baselining a concurrent
    agent's in-flight edit would silently swallow a regression the fence
    exists to catch. The two states usually agree; when they do not, this
    test fails immediately and names the file, which is the point.
    """

    def test_no_baseline_row_names_a_missing_file(self):
        missing = sorted(rel for rel in BASELINE_TESTS_DIR if not (REPO_ROOT / rel).exists())
        assert not missing, (
            "BASELINE_TESTS_DIR names file(s) that no longer exist — delete "
            "these rows:\n  " + "\n  ".join(missing)
        )

    def test_no_file_count_grows_or_silently_shrinks(self):
        current = _tests_dir_import_counts()
        growth = []
        shrink = []
        for rel in sorted(set(current) | set(BASELINE_TESTS_DIR)):
            have = current.get(rel, 0)
            base = BASELINE_TESTS_DIR.get(rel, 0)
            if have > base:
                growth.append(f"{rel}: {base} -> {have}")
            elif have < base:
                shrink.append(f"{rel}: {base} -> {have}")
        problems = []
        if growth:
            problems.append(
                "GROWTH — new function-level `ppxai` import(s). Hoist to module "
                "top. If it genuinely must run after a `monkeypatch`/env-change "
                "so module-level state resolves under the patch, that is a real "
                "reason (see `RETAINED_ON_PURPOSE` above for the `ppxai/` "
                "analogue) — but then raise this file's row in BASELINE_TESTS_DIR "
                "deliberately, in the same commit, with a comment saying why:\n  "
                + "\n  ".join(growth)
            )
        if shrink:
            problems.append(
                "SHRUNK — fewer function-level `ppxai` imports than the baseline "
                "records. Good, but lower the row(s) in BASELINE_TESTS_DIR to "
                "match, or the baseline drifts into a wish list:\n  "
                + "\n  ".join(shrink)
            )
        assert not problems, "\n\n".join(problems)
