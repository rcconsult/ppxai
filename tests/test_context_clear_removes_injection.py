"""`/context clear` removes what `ContextInjector` actually wrote.

Smoke defect 5 (2026-09-26): the removal regex expected a block the
injector has never produced, so `/context clear` reported "Cleared N" and
left every injected byte in history (~32k tokens, 25% of the window, before
and after). These tests feed the REAL injector's output, not a hand-written
imitation of it; the imitation is how the old regex stayed green.
"""

from __future__ import annotations

from types import SimpleNamespace

from ppxai.engine.context import ContextInjector
from ppxai.engine.session_ops import clear_injected_contexts
from ppxai.engine.types import Message


def _engine(messages, tracked):
    session = SimpleNamespace(messages=messages, _notify_messages_changed=lambda: None)
    return SimpleNamespace(session=session, _injected_contexts=list(tracked))


def _inject(tmp_path, files: dict[str, str], message: str):
    for name, body in files.items():
        (tmp_path / name).write_text(body, encoding="utf-8")
    enhanced, injected = ContextInjector(str(tmp_path)).inject_context(message)
    assert injected, "precondition: the injector must have injected something"
    return enhanced, injected


def test_a_single_injected_file_is_removed(tmp_path):
    enhanced, injected = _inject(tmp_path, {"a.py": "print('secret')\n"}, "explain @a.py")
    assert "**Attached context:**" in enhanced
    msg = Message("user", enhanced)
    engine = _engine([msg], injected)

    assert clear_injected_contexts(engine) == len(injected)
    assert "Attached context" not in msg.content
    assert "print('secret')" not in msg.content
    assert msg.content.startswith("explain ")


def test_several_files_and_content_with_its_own_fences_are_removed(tmp_path):
    fenced = "# Doc\n\n```bash\necho inner\n```\n\ntrailing text\n"
    enhanced, injected = _inject(
        tmp_path, {"a.py": "x = 1\n", "b.md": fenced}, "compare @a.py and @b.md"
    )
    msg = Message("user", enhanced)
    engine = _engine([msg], injected)

    clear_injected_contexts(engine)
    for leftover in ("x = 1", "echo inner", "trailing text", "Attached context"):
        assert leftover not in msg.content, leftover


def test_other_messages_are_untouched(tmp_path):
    enhanced, injected = _inject(tmp_path, {"a.py": "y = 2\n"}, "see @a.py")
    plain_user = Message("user", "a message with --- a rule in it")
    assistant = Message("assistant", "an answer\n\n---\n**Attached context:**\nnot mine")
    injected_msg = Message("user", enhanced)
    engine = _engine([plain_user, injected_msg, assistant], injected)

    clear_injected_contexts(engine)
    assert plain_user.content == "a message with --- a rule in it"
    assert assistant.content.endswith("not mine")
    assert "y = 2" not in injected_msg.content


def test_multimodal_text_parts_are_cleaned_too(tmp_path):
    enhanced, injected = _inject(tmp_path, {"a.py": "z = 3\n"}, "look @a.py")
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAA"}}
    msg = Message("user", [{"type": "text", "text": enhanced}, image])
    engine = _engine([msg], injected)

    clear_injected_contexts(engine)
    assert "z = 3" not in msg.content[0]["text"]
    assert msg.content[1] == image
