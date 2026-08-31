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

from unittest.mock import MagicMock, patch

import pytest


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
        import ppxai.engine.context as ctx_mod

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
        import ppxai.engine.context as ctx_mod

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
        from ppxai.commands.provider import handle_model_info

        result = handle_model_info(self._ctx(None), "openai", "gpt-5.6-terra")
        assert result is not None

    def test_the_hints_row_appears_when_hints_exist(self):
        """The feature that was dead. Asserting the row's CONTENT, because a
        no-raise test would pass against a block that silently does nothing."""
        from ppxai.commands.provider import handle_model_info

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
        from ppxai.commands.provider import handle_model_info

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
        import importlib

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
        import inspect

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
