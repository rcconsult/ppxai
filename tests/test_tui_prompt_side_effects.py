"""Rich and Textual consume the prompt side-effects (2026-09-21).

Before this, `grep -rn side_effect ppxai/tui ppxai/rich ppxai/rendering`
returned NOTHING: neither TUI read `CommandResult.side_effects` at all.
The visible consequence, reproduced against the real handler:

    handle_show(ctx, "@config")  # 3 matches
    RichRenderer.render(result)  # prints "ℹ 3 files match 'config'"
                                 # …and that is the whole interaction.

`prompt_quick_pick` is in `CLIENT_ROUND_TRIP_KINDS` precisely because
that failure is invisible — kinds are an open enum, so an unhandled one
looks exactly like a command that had nothing more to say.

These tests drive the REAL consumers:

  * Rich   — `consume_prompt_side_effects` (numbered list + number),
             and the re-dispatch in `CommandHandler.handle_command`.
  * Textual— `PPXAIDEApp._consume_prompt_side_effects` / the
             `QuickPickDialog` modal, driven with Textual's Pilot.

Escape hatches are asserted as hard as the happy path: a user who
answers nothing must cause NO dispatch, because the handler that asked
has not performed its action yet.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from textual.app import App, ComposeResult
from textual.widgets import Static

from ppxai.commands import handler as handler_mod
from ppxai.commands.handler import CommandHandler
from ppxai.commands.results import (
    MAX_PROMPT_RESUME_DEPTH,
    NotificationResult,
    ResultStatus,
    SideEffectKind,
    parse_prompt_text,
    parse_quick_pick,
    prompt_text_resume_args,
    resume_command_line,
)
from ppxai.rendering import rich_renderer
from ppxai.rendering.rich_renderer import consume_prompt_side_effects
from ppxai.tui import app as tui_app_mod
from ppxai.tui.app import PPXAIDEApp
from ppxai.tui.widgets.dialog import PromptDialog, QuickPickDialog


def _quick_pick_result(
    *, command: str = "checkpoint", items=None, title: str = "Pick one",
) -> NotificationResult:
    result = NotificationResult(status=ResultStatus.WARNING, message="ask")
    result.add_side_effect(
        SideEffectKind.PROMPT_QUICK_PICK,
        title=title,
        items=items or [
            {"label": "Cancel — keep all checkpoints", "value": "clear --no"},
            {"label": "Clear all 3 file checkpoints", "value": "clear --yes"},
        ],
        command_to_resume=command,
    )
    return result


def _prompt_text_result(*, original_args: str = "fix") -> NotificationResult:
    result = NotificationResult(status=ResultStatus.WARNING, message="too vague")
    result.add_side_effect(
        SideEffectKind.PROMPT_TEXT,
        title="I need more detail to run safely",
        question="What file or area?",
        command_to_resume="auto",
        original_args=original_args,
        placeholder="e.g. src/parser.py",
    )
    return result


# ===========================================================================
# The pure helpers both TUIs share (and neither re-derives)
# ===========================================================================

class TestPurePayloadHelpers:
    def test_resume_line_is_the_shape_the_js_clients_send(self):
        """`side-effects.js` dispatches `/${cmd} ${value}`; an
        in-process resume must be the same string, or the TUIs would be
        a second dispatch route with a second arg-parsing rule."""
        assert resume_command_line("checkpoint", "clear --yes") == \
            "/checkpoint clear --yes"

    def test_a_value_with_spaces_survives_intact(self):
        line = resume_command_line("edit", "--create my notes.txt")
        assert line == "/edit --create my notes.txt"
        # what the handler then receives as `args`
        assert line.split(maxsplit=1)[1] == "--create my notes.txt"

    def test_an_empty_value_does_not_leave_a_trailing_space(self):
        assert resume_command_line("show", "") == "/show"

    def test_prompt_text_uses_the_em_dash_contract(self):
        assert prompt_text_resume_args("fix", "the parser") == "fix — the parser"

    def test_prompt_text_without_original_args_is_just_the_reply(self):
        assert prompt_text_resume_args("", "the parser") == "the parser"

    @pytest.mark.parametrize("payload", [
        {},
        {"items": [{"label": "a", "value": "b"}]},          # no command
        {"command_to_resume": "show"},                       # no items
        {"command_to_resume": "show", "items": []},
        {"command_to_resume": "show", "items": "nope"},
        {"command_to_resume": "  ", "items": [{"value": "x"}]},
        {"command_to_resume": "show", "items": [{"label": "a"}]},  # no value
    ])
    def test_malformed_quick_pick_payloads_are_refused(self, payload):
        assert parse_quick_pick(payload) is None

    def test_a_missing_label_falls_back_to_the_value(self):
        parsed = parse_quick_pick(
            {"command_to_resume": "show", "items": [{"value": "/tmp/a.py"}]})
        assert parsed is not None
        assert parsed[2][0]["label"] == "/tmp/a.py"

    def test_prompt_text_prefers_the_title_then_the_question(self):
        assert parse_prompt_text(
            {"command_to_resume": "auto", "question": "why?"})[0] == "why?"
        assert parse_prompt_text(
            {"command_to_resume": "auto", "title": "T", "question": "why?"})[0] == "T"

    def test_malformed_prompt_text_is_refused(self):
        assert parse_prompt_text({"question": "why?"}) is None


# ===========================================================================
# Rich
# ===========================================================================

class TestRichQuickPick:
    def test_picking_returns_the_resume_line(self, monkeypatch):
        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "2")
        assert consume_prompt_side_effects(_quick_pick_result()) == \
            "/checkpoint clear --yes"

    def test_picking_the_first_row_cancels_the_destructive_action(self, monkeypatch):
        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "1")
        assert consume_prompt_side_effects(_quick_pick_result()) == \
            "/checkpoint clear --no"

    @pytest.mark.parametrize("answer", ["", "   ", "0", "9", "-1", "abc", "1.5"])
    def test_declining_dispatches_nothing(self, monkeypatch, answer):
        """Empty / zero / out-of-range / non-numeric all mean CANCEL.

        `Prompt.ask` is deliberately called WITHOUT `choices=`: with it,
        Rich re-asks forever on bad input, and a bare Enter would take
        the default — which for a picker whose second row deletes every
        checkpoint is the wrong reading of "the user just pressed
        Enter"."""
        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: answer)
        assert consume_prompt_side_effects(_quick_pick_result()) is None

    @pytest.mark.parametrize("boom", [KeyboardInterrupt, EOFError])
    def test_ctrl_c_and_eof_dispatch_nothing(self, monkeypatch, boom):
        def _raise(*a, **k):
            raise boom()
        monkeypatch.setattr(rich_renderer.Prompt, "ask", _raise)
        assert consume_prompt_side_effects(_quick_pick_result()) is None

    def test_a_result_with_no_side_effects_asks_nothing(self, monkeypatch):
        def _never(*a, **k):
            raise AssertionError("Prompt.ask must not be called")
        monkeypatch.setattr(rich_renderer.Prompt, "ask", _never)
        plain = NotificationResult(status=ResultStatus.INFO, message="hi")
        assert consume_prompt_side_effects(plain) is None

    def test_a_non_prompt_side_effect_asks_nothing(self, monkeypatch):
        def _never(*a, **k):
            raise AssertionError("Prompt.ask must not be called")
        monkeypatch.setattr(rich_renderer.Prompt, "ask", _never)
        result = NotificationResult(status=ResultStatus.INFO, message="hi")
        result.add_side_effect(SideEffectKind.OPEN_VIEWER, filepath="/tmp/x")
        assert consume_prompt_side_effects(result) is None


class TestRichPromptText:
    def test_a_reply_becomes_the_em_dash_resume(self, monkeypatch):
        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "src/parser.py")
        assert consume_prompt_side_effects(_prompt_text_result()) == \
            "/auto fix — src/parser.py"

    def test_an_empty_reply_dispatches_nothing(self, monkeypatch):
        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "  ")
        assert consume_prompt_side_effects(_prompt_text_result()) is None

    def test_ctrl_c_dispatches_nothing(self, monkeypatch):
        def _raise(*a, **k):
            raise KeyboardInterrupt()
        monkeypatch.setattr(rich_renderer.Prompt, "ask", _raise)
        assert consume_prompt_side_effects(_prompt_text_result()) is None


class TestRichReDispatch:
    """`CommandHandler.handle_command` must send the answer back down
    the SAME path a typed line takes — not a private resume route."""

    def _handler(self):
        return CommandHandler.__new__(CommandHandler)

    def test_the_answer_is_dispatched_exactly_once(self, monkeypatch):
        dispatched: list[str] = []
        asked = {"n": 0}

        def _fake_ask(*a, **k):
            asked["n"] += 1
            return "2"

        monkeypatch.setattr(rich_renderer.Prompt, "ask", _fake_ask)

        spec = MagicMock()
        spec.handler = lambda ctx, args: (
            _quick_pick_result() if args.strip() == "clear"
            else NotificationResult(status=ResultStatus.SUCCESS, message="done")
        )
        monkeypatch.setattr(handler_mod.CommandFactory, "get", lambda name: spec)
        monkeypatch.setattr(handler_mod.CommandFactory, "names_for_client_action",
                            lambda action: ())
        monkeypatch.setattr(handler_mod, "RichCommandContext", lambda h: MagicMock())
        monkeypatch.setattr(
            rich_renderer.RichRenderer, "render",
            staticmethod(lambda result: dispatched.append(result.message)))

        h = self._handler()
        h.handle_command("/checkpoint clear")

        assert asked["n"] == 1, "the user must be asked exactly once"
        assert dispatched == ["ask", "done"], (
            "the resumed command must be rendered too — one prompt, one resume")

    def test_declining_re_dispatches_nothing(self, monkeypatch):
        rendered: list[str] = []
        calls = {"n": 0}

        def _spec_handler(ctx, args):
            calls["n"] += 1
            return _quick_pick_result()

        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "")
        spec = MagicMock()
        spec.handler = _spec_handler
        monkeypatch.setattr(handler_mod.CommandFactory, "get", lambda name: spec)
        monkeypatch.setattr(handler_mod.CommandFactory, "names_for_client_action",
                            lambda action: ())
        monkeypatch.setattr(handler_mod, "RichCommandContext", lambda h: MagicMock())
        monkeypatch.setattr(
            rich_renderer.RichRenderer, "render",
            staticmethod(lambda result: rendered.append(result.message)))

        self._handler().handle_command("/checkpoint clear")
        assert calls["n"] == 1, "no resume must reach the handler"
        assert rendered == ["ask"]

    def test_the_chain_is_bounded(self, monkeypatch):
        """A handler that ALWAYS prompts would loop forever against a
        client that always answers — each hop is a fresh stateless
        dispatch with no server memory of the previous one."""
        calls = {"n": 0}

        def _always_prompts(ctx, args):
            calls["n"] += 1
            return _quick_pick_result()

        monkeypatch.setattr(rich_renderer.Prompt, "ask", lambda *a, **k: "2")
        spec = MagicMock()
        spec.handler = _always_prompts
        monkeypatch.setattr(handler_mod.CommandFactory, "get", lambda name: spec)
        monkeypatch.setattr(handler_mod.CommandFactory, "names_for_client_action",
                            lambda action: ())
        monkeypatch.setattr(handler_mod, "RichCommandContext", lambda h: MagicMock())
        monkeypatch.setattr(rich_renderer.RichRenderer, "render",
                            staticmethod(lambda result: None))

        self._handler().handle_command("/checkpoint clear")
        assert calls["n"] == MAX_PROMPT_RESUME_DEPTH, (
            f"expected the chain to stop at {MAX_PROMPT_RESUME_DEPTH} "
            f"dispatches, got {calls['n']}")


# ===========================================================================
# Textual
# ===========================================================================

async def _noop() -> None:
    return None


class _StubApp:
    """The three app members the consumer touches, nothing else.

    `_consume_prompt_side_effects` and `_resume_after_prompt` are taken
    unbound off the REAL class, so this drives production code rather
    than a copy of it — the same trick the run-consent tests use.
    """

    def __init__(self):
        self.pushed: list = []
        self.workers: list = []
        self.system_messages: list[str] = []
        self._chat_view = MagicMock()
        self._chat_view.add_system_message = self.system_messages.append

    def push_screen(self, screen, callback):
        self.pushed.append((screen, callback))

    def run_worker(self, awaitable):
        self.workers.append(awaitable)
        awaitable.close()      # never scheduled; the call itself is the signal

    def _handle_command(self, command, _resume_depth=0):
        """Records the dispatch and hands back a closable awaitable.

        The REAL `_handle_command` is a coroutine function, so
        `_resume_after_prompt` calls it and passes the coroutine to
        `run_worker`. A coroutine records nothing until it is scheduled,
        which a stub must not depend on — so this records eagerly and
        returns a throwaway coroutine for `run_worker` to close.
        """
        self.dispatched = (command, _resume_depth)
        return _noop()


def _stub():
    app = _StubApp()
    app._consume_prompt_side_effects = (
        lambda result, depth: PPXAIDEApp._consume_prompt_side_effects(app, result, depth))
    app._resume_after_prompt = (
        lambda line, depth: PPXAIDEApp._resume_after_prompt(app, line, depth))
    return app


class TestTextualConsumer:
    def test_a_quick_pick_pushes_a_modal(self):
        app = _stub()
        app._consume_prompt_side_effects(_quick_pick_result(), 0)
        assert len(app.pushed) == 1
        screen, _ = app.pushed[0]
        assert isinstance(screen, QuickPickDialog)
        assert [i["label"] for i in screen.items][0].startswith("Cancel")

    def test_the_callback_dispatches_the_chosen_value(self):
        app = _stub()
        app._consume_prompt_side_effects(_quick_pick_result(), 0)
        _, callback = app.pushed[0]
        callback("clear --yes")
        assert app.workers, "a worker must carry the resume"
        assert app.dispatched == ("/checkpoint clear --yes", 1)

    def test_dismissing_dispatches_nothing(self):
        app = _stub()
        app._consume_prompt_side_effects(_quick_pick_result(), 0)
        _, callback = app.pushed[0]
        callback(None)          # Escape / Cancel button
        assert app.workers == []

    def test_an_empty_value_dispatches_nothing(self):
        app = _stub()
        app._consume_prompt_side_effects(_quick_pick_result(), 0)
        app.pushed[0][1]("")
        assert app.workers == []

    def test_prompt_text_pushes_a_prompt_dialog(self):
        app = _stub()
        app._consume_prompt_side_effects(_prompt_text_result(), 0)
        screen, callback = app.pushed[0]
        assert isinstance(screen, PromptDialog)
        callback("src/parser.py")
        assert app.dispatched == ("/auto fix — src/parser.py", 1)

    def test_prompt_text_cancel_dispatches_nothing(self):
        app = _stub()
        app._consume_prompt_side_effects(_prompt_text_result(), 0)
        app.pushed[0][1](None)
        assert app.workers == []

    def test_a_malformed_payload_pushes_nothing(self):
        app = _stub()
        result = NotificationResult(status=ResultStatus.INFO, message="x")
        result.add_side_effect(SideEffectKind.PROMPT_QUICK_PICK, items=[])
        app._consume_prompt_side_effects(result, 0)
        assert app.pushed == []

    def test_the_chain_is_bounded(self):
        app = _stub()
        app._resume_after_prompt("/checkpoint clear --yes", MAX_PROMPT_RESUME_DEPTH - 1)
        assert app.workers == []
        assert any("Stopped after" in m for m in app.system_messages)

    def test_one_below_the_bound_still_dispatches(self):
        app = _stub()
        app._resume_after_prompt("/checkpoint clear --yes", MAX_PROMPT_RESUME_DEPTH - 2)
        assert app.workers


class TestQuickPickDialogWidget:
    """Driven with a real Textual Pilot — the modal must resolve with the
    item's VALUE (not its label) and must leave the screen stack clean."""

    async def test_selecting_resolves_with_the_value(self):
        picked: list = []

        class Host(App):
            def compose(self) -> ComposeResult:
                yield Static("host")

            def on_mount(self) -> None:
                self.push_screen(
                    QuickPickDialog(
                        title="Delete all 3?",
                        items=[
                            {"label": "Cancel — keep all", "value": "clear --no"},
                            {"label": "Clear all 3", "value": "clear --yes"},
                        ],
                    ),
                    picked.append,
                )

        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            assert isinstance(app.screen, QuickPickDialog)
            await pilot.press("down")      # highlight row 2
            await pilot.press("enter")
            await pilot.pause()
            assert picked == ["clear --yes"]
            assert not isinstance(app.screen, QuickPickDialog), \
                "the modal must be off the stack"

    async def test_escape_resolves_with_none_and_pops_the_modal(self):
        picked: list = []

        class Host(App):
            def compose(self) -> ComposeResult:
                yield Static("host")

            def on_mount(self) -> None:
                self.push_screen(
                    QuickPickDialog(
                        title="Delete all 3?",
                        items=[
                            {"label": "Cancel — keep all", "value": "clear --no"},
                            {"label": "Clear all 3", "value": "clear --yes"},
                        ],
                    ),
                    picked.append,
                )

        app = Host()
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("escape")
            await pilot.pause()
            assert picked == [None]
            assert not isinstance(app.screen, QuickPickDialog), \
                "the modal must be off the stack"


class TestTextualHandleCommandReachesTheConsumer:
    """The Rich tests above drive `handle_command`, so deleting Rich's
    consumer call fails them. Textual's consumer is a separate method,
    and a test that only calls that method directly would stay GREEN if
    `_handle_command` stopped calling it — a fence that does not look.
    This drives the real `_handle_command`.
    """

    @staticmethod
    def _app():
        app = _stub()
        app._debug_logging = False
        app._log = MagicMock()
        app._event_bus = MagicMock()
        return app

    async def _run(self, app, monkeypatch, result):
        spec = MagicMock()
        spec.handler = lambda ctx, args: result
        monkeypatch.setattr(tui_app_mod.CommandFactory, "get", lambda name: spec)
        monkeypatch.setattr(tui_app_mod.CommandFactory, "names_for_client_action",
                            lambda action: ())
        rendered = []

        class _Renderer:
            def __init__(self, _app):
                pass

            async def render(self, res):
                rendered.append(res)

        monkeypatch.setattr(tui_app_mod, "TextualRenderer", _Renderer)
        await PPXAIDEApp._handle_command(app, "/checkpoint clear")
        return rendered

    async def test_a_quick_pick_result_raises_the_modal(self, monkeypatch):
        app = self._app()
        rendered = await self._run(app, monkeypatch, _quick_pick_result())
        assert rendered, "the result must still be rendered"
        assert len(app.pushed) == 1, (
            "_handle_command must call _consume_prompt_side_effects — without "
            "it `/checkpoint clear` renders a warning and nothing else ever "
            "happens (the pre-2026-09-21 behaviour)")
        assert isinstance(app.pushed[0][0], QuickPickDialog)

    async def test_a_plain_result_raises_nothing(self, monkeypatch):
        app = self._app()
        plain = NotificationResult(status=ResultStatus.SUCCESS, message="done")
        await self._run(app, monkeypatch, plain)
        assert app.pushed == []
