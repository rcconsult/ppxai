"""FIX 3 (v1.19.3): `agent_runs.CATEGORIES` must name every category an
`emit_event(...)` call actually persists.

`task_runner.py`'s T2 filesystem-seal path (`path_denied`, ~line 433) emits
`category="filesystem"`, but `CATEGORIES` (`ppxai/engine/agent_runs.py`)
listed only `("lifecycle", "tool", "network", "consent", "result")` — the
category existed on the wire but not in the vocabulary a reader (`/doctor`,
a future strict `?category=` validator, a client-side legend) would check
against. Grepped for anything downstream that VALIDATES against
`CATEGORIES` or builds a client-side filter list from it: nothing does
today (`ppxai/server/routes/agent_v1.py`'s `?category=` filter is a free-form
comma-split with no membership check; no web/VSCode file enumerates the run-
event category vocabulary) — so this was a silent gap, not a live bug, and
this fence is what keeps it from becoming one.

This scan is deliberately narrow: `category=` is also a kwarg on
`CommandSpec` (`ppxai/commands/*.py` — "coding", "navigation", "utility",
"custom", ... — the SLASH-COMMAND help taxonomy, a completely unrelated
vocabulary). Only calls whose attribute is literally `emit_event` are in
scope.
"""

from __future__ import annotations

import ast
import textwrap
from pathlib import Path

from ppxai.engine.agent_runs import CATEGORIES

REPO_ROOT = Path(__file__).resolve().parent.parent
PPXAI_DIR = REPO_ROOT / "ppxai"


def _literal_emit_event_categories(tree: ast.AST) -> set[str]:
    """Every string-literal `category=` value passed to a call named
    `emit_event` (`x.emit_event(...)` or bare `emit_event(...)`) in `tree`.
    Non-literal values (a variable passthrough, e.g. `AgentRunRegistry.
    emit_event`'s own `category=category` forwarding) are not this
    vocabulary's producer and are skipped — they carry whatever the CALLER
    passed, already counted at the caller's own literal site.
    """
    found: set[str] = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else (
            func.id if isinstance(func, ast.Name) else None
        )
        if name != "emit_event":
            continue
        for kw in node.keywords:
            if kw.arg == "category" and isinstance(kw.value, ast.Constant) and isinstance(kw.value.value, str):
                found.add(kw.value.value)
    return found


def _scan_repo() -> set[str]:
    all_categories: set[str] = set()
    for path in PPXAI_DIR.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        all_categories |= _literal_emit_event_categories(tree)
    return all_categories


class TestCategoriesCoverEveryEmitEventCall:

    def test_every_literal_category_used_is_declared(self):
        used = _scan_repo()
        undeclared = used - set(CATEGORIES)
        assert undeclared == set(), (
            f"emit_event(...) uses categor{'y' if len(undeclared) == 1 else 'ies'} "
            f"{sorted(undeclared)} not in agent_runs.CATEGORIES {CATEGORIES} — "
            "add it there (and to the `?category=` docstring in "
            "server/routes/agent_v1.py) or fix the call site."
        )

    def test_filesystem_is_declared(self):
        """The specific gap this fix closes: task_runner.py's `path_denied`
        (T2 filesystem seal) emits category="filesystem"."""
        assert "filesystem" in CATEGORIES

    def test_scanner_finds_the_real_filesystem_call_site(self):
        """Sanity: the scanner isn't just reading the declared tuple back —
        it actually walks task_runner.py and finds the literal."""
        used = _scan_repo()
        assert "filesystem" in used

    def test_planted_undeclared_category_is_caught(self):
        """Control: a call site using a category nothing declares must be
        flagged, proving the scan isn't vacuous."""
        bad_source = """
        def f():
            registry.emit_event(run_id, "bogus_event", category="not_a_real_category")
        """
        tree = ast.parse(textwrap.dedent(bad_source))
        used = _literal_emit_event_categories(tree)
        assert used == {"not_a_real_category"}
        assert used - set(CATEGORIES) == {"not_a_real_category"}

    def test_planted_declared_category_is_not_flagged(self):
        """Sanity: a call using an ALREADY-declared category is not a false
        positive."""
        bad_source = """
        def f():
            registry.emit_event(run_id, "tool_call", category="tool")
        """
        tree = ast.parse(textwrap.dedent(bad_source))
        used = _literal_emit_event_categories(tree)
        assert used - set(CATEGORIES) == set()

    def test_command_spec_category_kwarg_is_not_conflated(self):
        """`CommandSpec(..., category="coding")` is a different vocabulary
        (the slash-command help taxonomy) and must not be swept in just
        because the kwarg name matches — only calls literally named
        `emit_event` count."""
        bad_source = """
        def f():
            CommandSpec(name="x", category="coding")
        """
        tree = ast.parse(textwrap.dedent(bad_source))
        assert _literal_emit_event_categories(tree) == set()
