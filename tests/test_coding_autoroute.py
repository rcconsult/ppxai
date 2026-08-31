"""Item 30 (v1.18.8 Phase E): the coding auto-route notice must reach EVERY
client, not just the Rich TUI console.

`_execute_ai_task` used to `console.print(...)` the "Auto-routed to <model>"
notice, which is invisible to web/VSCode (server-side stdout). Those clients
render `AIResponseResult.content` and only fall back to `message` when content
is empty — so the notice now rides in `content`.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from ppxai.commands.coding import _execute_ai_task
from ppxai.commands.results import AIResponseResult, ResultStatus
from ppxai.engine.types import Event, EventType

_AI_OUTPUT = "Here you go:\n\n```python\ndef foo():\n    return 1\n```\n"


def _make_context(*, auto_route: bool, model: str = "base-model"):
    def fake_chat(*args, **kwargs):
        async def _gen():
            yield Event(type=EventType.STREAM_CHUNK, data=_AI_OUTPUT)
        return _gen()

    engine = MagicMock()
    engine.model = model
    engine.chat = fake_chat
    engine.set_model = MagicMock()

    ctx = MagicMock()
    ctx.engine_client = engine
    ctx.get_provider.return_value = "openai"
    ctx.get_model.return_value = model
    ctx.get_auto_route.return_value = auto_route
    return ctx


def test_auto_route_notice_rides_in_content():
    ctx = _make_context(auto_route=True)
    with patch("ppxai.commands.coding.get_coding_model", return_value="coding-model"):
        result = _execute_ai_task(ctx, "generate", "make foo", "Generating...")

    assert isinstance(result, AIResponseResult)
    assert result.status == ResultStatus.SUCCESS
    # The notice is in content (the field web/VSCode actually render).
    assert result.content.startswith("_Auto-routed to coding-model")
    assert "disable with `/autoroute off`" in result.content
    # The AI output is preserved after the notice.
    assert "def foo():" in result.content
    # Code blocks are extracted from the raw output, not the notice.
    assert result.code_blocks == [{"language": "python", "code": "def foo():\n    return 1"}]


def test_no_notice_when_auto_route_disabled():
    ctx = _make_context(auto_route=False)
    with patch("ppxai.commands.coding.get_coding_model", return_value="coding-model"):
        result = _execute_ai_task(ctx, "generate", "make foo", "Generating...")

    assert isinstance(result, AIResponseResult)
    assert "Auto-routed" not in result.content
    assert result.content.startswith("Here you go:")


def test_no_notice_when_already_on_coding_model():
    # auto_route on, but the active model already IS the coding model → no switch,
    # no notice.
    ctx = _make_context(auto_route=True, model="coding-model")
    with patch("ppxai.commands.coding.get_coding_model", return_value="coding-model"):
        result = _execute_ai_task(ctx, "generate", "make foo", "Generating...")

    assert "Auto-routed" not in result.content
