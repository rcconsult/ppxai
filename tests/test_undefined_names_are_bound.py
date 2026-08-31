"""The four F821 sites, fenced (debt Item 67).

`ruff` found ten `undefined-name` findings in production code — names used
but never bound. None was in a test, and none had a test: each sat on a path
nothing exercised, so the `NameError` waited for a real user.

Three were genuinely reachable, and the `context.py` pair is the sharpest
shape in the set: both uses sit **inside `except` handlers**, so the failure
path destroyed the evidence of the original failure. A handler that raises
`NameError` turns "bootstrap config check failed, carrying on" into a crash
that names the wrong problem.

The tests below exercise the four sites rather than asserting the imports
exist, because an import assertion passes as soon as someone adds the name
and says nothing about whether the code around it works. Each one fails with
`NameError` against the pre-fix source.
"""

import ast
import importlib
import inspect
import pathlib
from unittest.mock import MagicMock, patch

import pytest

import ppxai.engine.context as ctx_mod
from ppxai.commands.provider import handle_model_info


class TestContextExceptionHandlersSurvive:
    """`logger` in `engine/context.py:212,246` — used, never imported.

    The regression these prevent is not "bootstrap breaks". It is that when
    bootstrap config is unreadable, the *handler* raises instead of degrading,
    and the traceback names `logger` rather than the config problem.
    """

    @pytest.mark.parametrize(
        "method", ["find_bootstrap_files", "find_bootstrap_files_with_scopes"]
    )
    def test_the_handler_degrades_instead_of_raising(self, method, tmp_path):
        injector = ctx_mod.ContextInjector(working_dir=str(tmp_path))
        with patch.object(
            ctx_mod, "is_bootstrap_enabled", side_effect=RuntimeError("config unreadable")
        ):
            # Must not raise. The value is allowed to be anything the method
            # considers empty-ish; what matters is that control returns.
            getattr(injector, method)()

    def test_the_module_has_a_logger_to_log_with(self):
        """Source-level companion to the behavioural test above.

        The behavioural test would also pass if someone deleted the logging
        call entirely. That would lose the diagnostic the handler exists to
        emit, so pin that a logger is actually present.
        """
        assert hasattr(ctx_mod, "logger"), (
            "engine/context.py logs from its exception handlers; without a "
            "module logger those handlers raise NameError"
        )


class TestModelInfoResolvesItsBootstrapContext:
    """`bootstrap_ctx` in `commands/provider.py:318,320` — never assigned.

    This one had never worked: the block raised `NameError` on *every*
    invocation, so `/model info`'s Hints row could not have appeared for
    anyone since it was written.
    """

    @staticmethod
    def _ctx(bootstrap_context):
        ctx = MagicMock()
        ctx.engine_client._bootstrap_context = bootstrap_context
        return ctx

    def test_it_runs_with_no_bootstrap_context(self):
        result = handle_model_info(self._ctx(None), "openai", "gpt-5.6-terra")
        assert result is not None

    def test_the_hints_row_appears_when_hints_exist(self):
        """The feature that was dead. Asserting the row's CONTENT, because a
        no-raise test would pass against a block that silently does nothing."""
        bootstrap = MagicMock()
        bootstrap.get_active_hints_for.return_value = {
            "provider_hints": ["a"],
            "model_hints": ["b", "c"],
        }
        result = handle_model_info(self._ctx(bootstrap), "openai", "gpt-5.6-terra")

        assert bootstrap.get_active_hints_for.called
        pairs = dict(getattr(result, "pairs", None) or getattr(result, "items", {}))
        assert pairs.get("Hints") == "2 model, 1 provider"

    def test_a_context_without_the_attribute_does_not_crash(self):
        """`_bootstrap_context` is Optional on the client and absent on a
        minimal double, which is why the resolution uses `getattr`."""
        ctx = MagicMock()
        ctx.engine_client = MagicMock(spec=[])
        assert handle_model_info(ctx, "openai", "gpt-5.6-terra") is not None


class TestArtifactPanelCanNameItsRenderer:
    """`TextualRenderer` in `tui/widgets/artifact_panel.py:104,174`.

    Annotation-only, so nothing raised at runtime — but the annotations named
    a real class the module never imported, which makes them undecidable for
    any reader or type checker. The import is safe: `textual_renderer` does
    not import this module, so there is no cycle.
    """

    def test_the_annotated_type_is_in_scope(self):
        pytest.importorskip("textual")
        import ppxai.tui.widgets.artifact_panel as panel
        from ppxai.rendering.textual_renderer import TextualRenderer

        assert panel.TextualRenderer is TextualRenderer

    def test_importing_it_creates_no_cycle(self):
        """The reason it was never imported, tested rather than assumed."""
        pytest.importorskip("textual")
        importlib.import_module("ppxai.rendering.textual_renderer")
        importlib.import_module("ppxai.tui.widgets.artifact_panel")


class TestStatusBarIsBoundWhereItIsUsed:
    """`status_bar` in `tui/app.py:1094-1099` — used, never bound.

    A copy of the badge block in `on_mount`, which has the local alias this
    copy lost. Source-level, because reaching that branch needs a mounted
    Textual app with a live engine; the binding is what was missing and the
    binding is what this pins.
    """

    def test_the_badge_block_binds_before_it_uses(self):
        pytest.importorskip("textual")
        from ppxai.tui.app import PPXAIDEApp

        src = inspect.getsource(PPXAIDEApp._handle_command)
        assert "status_bar = self._status_bar" in src, (
            "the agent-badge block uses `status_bar`; without a binding it "
            "raises NameError on every /tools or /agent command"
        )
        # The binding must come before the uses, or it fences nothing.
        assert src.index("status_bar = self._status_bar") < src.index(
            'status_bar.add_badge("agent"'
        )


class TestEveryExportedNameExists:
    """`__all__` must not promise names the module does not define (F822).

    `ppxai/server/session_manager.py` listed `get_session_manager` and
    `get_idle_timeout` in `__all__`. Both are real functions — but they live
    in `config/paths.py` and `server/state.py`, and this module never
    re-exported them. The entries were left behind by the v1.19.1 move that
    the module's own comment describes.

    Nothing star-imported the module, so nothing broke; the cost was a
    module advertising an interface it does not have. This is the same
    family as the F821s above — a name that resolves to nothing — which is
    why it is fenced in the same file.

    Written as a sweep rather than a check of that one module: the failure
    mode is a name left behind by a move, and moves happen anywhere.
    """

    @staticmethod
    def _modules_with_dunder_all():
        root = pathlib.Path(__file__).resolve().parent.parent / "ppxai"
        for path in sorted(root.rglob("*.py")):
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in tree.body:
                if not isinstance(node, ast.Assign):
                    continue
                if not any(
                    isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets
                ):
                    continue
                if isinstance(node.value, (ast.List, ast.Tuple)):
                    names = [
                        e.value
                        for e in node.value.elts
                        if isinstance(e, ast.Constant) and isinstance(e.value, str)
                    ]
                    if names:
                        yield path, tree, names

    def test_the_sweep_finds_modules_to_check(self):
        """Guard against a vacuous pass if the AST walk stops matching."""
        found = list(self._modules_with_dunder_all())
        assert found, "no module with a literal __all__ was found — the sweep is broken"

    def test_no_module_exports_a_name_it_does_not_define(self):
        broken = []
        for path, tree, names in self._modules_with_dunder_all():
            defined = set()
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    defined.add(node.name)
                elif isinstance(node, ast.Name) and isinstance(node.ctx, ast.Store):
                    defined.add(node.id)
                elif isinstance(node, ast.alias):
                    defined.add((node.asname or node.name).split(".")[0])
            missing = [n for n in names if n not in defined]
            if missing:
                broken.append(f"{path.name}: {missing}")

        assert not broken, (
            "these modules list names in __all__ that they neither define nor "
            "import, so `from <mod> import *` raises AttributeError and the "
            "module advertises an interface it does not have: " + "; ".join(broken)
        )
