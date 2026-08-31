"""R15 regression tests: server-side guard against context-only chat requests.

When a client (notably the VSCode extension) auto-prepends a
`[Context: Working in VSCode workspace "..." at ...]` block to an empty
user message, the provider sees only that synthetic context block. That
request has no real user prompt to answer, and strict-alternation
providers like Perplexity reject it with a 400.

The server now rejects those requests before dispatching them, returning
an SSE error event without touching the provider.
"""

import asyncio
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from ppxai.server.routes.chat import is_empty_or_context_only
from ppxai.server.routes.chat import router as chat_router
from ppxai.server.state import Session, get_session

# ---------------------------------------------------------------------------
# Pure function: is_empty_or_context_only
# ---------------------------------------------------------------------------


class TestIsEmptyOrContextOnly:
    """Detection of chat bodies that carry no real user prompt."""

    def test_empty_string(self):
        assert is_empty_or_context_only("") is True

    def test_whitespace_only(self):
        assert is_empty_or_context_only("   \n\t  ") is True

    def test_bare_context_block(self):
        msg = '[Context: Working in VSCode workspace "ppxai" at /Users/rado/git/utils/ppxai]'
        assert is_empty_or_context_only(msg) is True

    def test_context_block_with_trailing_newlines(self):
        msg = '[Context: Working in VSCode workspace "ppxai" at /home/user/p]\n\n'
        assert is_empty_or_context_only(msg) is True

    def test_multiple_context_blocks(self):
        """A client that accidentally prepended twice should still be caught."""
        msg = "[Context: workspace A]\n[Context: workspace B]\n"
        assert is_empty_or_context_only(msg) is True

    def test_real_prompt_passes(self):
        assert is_empty_or_context_only("Hello, how are you?") is False

    def test_context_plus_real_prompt_passes(self):
        """The common case — context preamble followed by a real user question."""
        msg = (
            '[Context: Working in VSCode workspace "ppxai" at /path]\n\n'
            "What does this function do?"
        )
        assert is_empty_or_context_only(msg) is False

    def test_context_like_text_inside_prompt_passes(self):
        """Mentioning '[Context:' in a real question must not trigger the guard."""
        msg = "Why did I see the log line '[Context: foo]' in my output?"
        assert is_empty_or_context_only(msg) is False


# ---------------------------------------------------------------------------
# Integration: POST /chat via TestClient
# ---------------------------------------------------------------------------


def _make_session(engine_chat_mock):
    """Session with an engine whose .chat() is the supplied mock."""
    from ppxai.engine.app_state import AppState

    engine = MagicMock()
    engine.provider_name = "perplexity"
    engine.model = "sonar-pro"
    engine.tools_enabled = False
    engine.auto_inject_context = False
    engine.state = AppState(initial={
        "provider": "perplexity",
        "model": "sonar-pro",
        "tools_enabled": False,
    })
    engine.file_store = None
    engine.has_vision_sidecar = lambda: False
    # No shell-CLI image route either — so an image on the non-vision model has
    # no consumable path and must fail loud (Item 24).
    engine.can_shell_process_images = lambda: False
    engine.chat = engine_chat_mock
    return Session(id="test-r15", engine=engine, lock=asyncio.Lock())


@pytest.fixture
def chat_mock():
    """Async generator mock — if called, the test has failed to block the request."""
    async def _unused(*_args, **_kwargs):
        yield None  # pragma: no cover
        raise AssertionError("engine.chat() should not have been called")
    mock = MagicMock(side_effect=_unused)
    return mock


@pytest.fixture
def client(chat_mock):
    app = FastAPI()
    app.include_router(chat_router)
    session = _make_session(chat_mock)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app), chat_mock


def _sse_body(resp) -> str:
    """Drain an SSE response into a single string for assertions."""
    return b"".join(resp.iter_bytes()).decode("utf-8")


class TestChatEndpointR15Guard:

    def test_empty_message_rejected_without_engine_call(self, client):
        tc, chat_mock = client
        resp = tc.post("/chat", json={"message": ""})
        assert resp.status_code == 200  # SSE uses 200 + error event
        body = _sse_body(resp)
        assert '"type": "error"' in body
        assert "Empty chat message" in body
        chat_mock.assert_not_called()

    def test_context_only_message_rejected(self, client):
        tc, chat_mock = client
        msg = '[Context: Working in VSCode workspace "ppxai" at /Users/rado/git/utils/ppxai]'
        resp = tc.post("/chat", json={"message": msg})
        assert resp.status_code == 200
        body = _sse_body(resp)
        assert '"type": "error"' in body
        assert "Empty chat message" in body
        chat_mock.assert_not_called()

    def test_context_with_trailing_newlines_rejected(self, client):
        tc, chat_mock = client
        msg = '[Context: workspace "x" at /p]\n\n'
        resp = tc.post("/chat", json={"message": msg})
        body = _sse_body(resp)
        assert '"type": "error"' in body
        chat_mock.assert_not_called()

    def test_real_message_passes_guard(self, client):
        """The guard must not break normal chats."""
        tc, chat_mock = client
        # Use an async generator that yields nothing but completes, so
        # the route can dispatch without actually streaming.
        async def _empty_stream(*_args, **_kwargs):
            if False:
                yield  # make it a generator
        chat_mock.side_effect = _empty_stream

        resp = tc.post("/chat", json={"message": "What is 2 + 2?"})
        assert resp.status_code == 200
        chat_mock.assert_called_once()

    def test_context_plus_real_message_passes_guard(self, client):
        tc, chat_mock = client
        async def _empty_stream(*_args, **_kwargs):
            if False:
                yield
        chat_mock.side_effect = _empty_stream

        msg = (
            '[Context: Working in VSCode workspace "ppxai" at /path]\n\n'
            "Explain the alternation validator."
        )
        resp = tc.post("/chat", json={"message": msg})
        assert resp.status_code == 200
        chat_mock.assert_called_once()


# ---------------------------------------------------------------------------
# Item 24 (v1.19.0 review fix): a hard attachment failure BLOCKS the send.
# An image on a text-only model with no VL sidecar / shell route escalates to
# a severity="error" warning; the route must emit that warning + an error and
# NEVER call the provider — not stream a completion over an "[Attachment
# error: ...]" placeholder as if the model had read the file.
# ---------------------------------------------------------------------------

_RED_PIXEL_PNG_B64 = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8DwHwAFAQH/c4"
    "X0gAAAAABJRU5ErkJggg=="
)


def _non_vision_client(chat_mock):
    """A /chat client whose engine is on a genuinely non-vision model
    ("text-only-model" — supports_vision=False), with no VL sidecar and no
    shell-CLI image route, so an image attachment has no consumable path."""
    session = _make_session(chat_mock)
    session.engine.model = "text-only-model"
    session.engine.provider_name = "custom"
    app = FastAPI()
    app.include_router(chat_router)
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


class TestItem24BlocksUnreadableAttachment:
    def test_image_on_non_vision_model_blocks_send(self, chat_mock):
        tc = _non_vision_client(chat_mock)
        resp = tc.post("/chat", json={
            "message": "what is in this image?",
            "files": [{
                "name": "shot.png",
                "media_type": "image/png",
                "data": _RED_PIXEL_PNG_B64,
            }],
        })
        assert resp.status_code == 200  # SSE: 200 + error event
        body = _sse_body(resp)
        # The structured vision warning is surfaced...
        assert '"type": "warning"' in body
        assert "vision_unsupported" in body
        # ...and the send is terminated with an error, never reaching the model.
        assert '"type": "error"' in body
        chat_mock.assert_not_called()
