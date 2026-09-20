"""Provider hierarchy compliance (v1.16.0 Step 1; interface re-derived 2026-09-20).

Verifies that all providers inherit from `BaseProvider` and expose the
methods the engine actually calls.

**Why this list was rewritten.** `REQUIRED_METHODS` asserts with `hasattr`,
which proves only that a name exists and is callable — nothing about
signature, return type or behaviour. That is strong enough to make a method
LOOK contractual and too weak to make it work, and the list had drifted in
both directions:

- It required `chat_sync_simple`, which was **never called anywhere in the
  repo's history** and was not even declared on `BaseProvider`. Four
  providers implemented it independently and they had silently diverged —
  `openai_native` routed by wire, Perplexity hardcoded chat-completions.
  The test is what kept recruiting implementations. Deleted 2026-09-20.
- It required `validate_config` and `needs_tool`, both dead. `needs_tool`
  had also been superseded by the live `config.providers.provider_needs_tool`.
  Deleted.
- It listed five `_`-prefixed helpers (`_get_generation_params`,
  `_get_max_tokens`, `_format_error`, `_log_error_traceback`,
  `_parse_usage`) as "interface". They have **zero** callers outside
  `providers/` — they are shared base-class implementation, which is a
  different thing. Split into their own list below so the distinction
  survives.
- It omitted **`oneshot`**, the one method besides `chat` that is genuinely
  `@abstractmethod` on the base and is driven across the seam by
  `server/routes/oneshot.py`. Added.

**The real seam is four methods wide**, and `ppxai/engine/` is its only
consumer: `chat` and `get_facts_for_model` (engine/chat.py), `list_models`
(engine/provider_ops.py), `oneshot` (server/routes/oneshot.py). All four
apps and the ppxai-sre sister repo reach providers exclusively through
`EngineClient` and never touch a provider object.

`get_capabilities` is kept despite having no production caller: it is the
endpoint-record accessor mandated by ADR 0012 §2 Q0e ("two records, two
accessors") and fenced by `TestTheTwoAccessors` below. The no-instance path
is served by `facts_resolver.capabilities_without_an_instance`.
"""

from unittest.mock import MagicMock, patch

import pytest

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.providers.perplexity import PerplexityProvider

# All provider classes to test
ALL_PROVIDERS = [
    OpenAICompatibleProvider,
    PerplexityProvider,
    OpenAINativeProvider,
    GeminiProvider,
]


class TestProviderInheritance:
    """Verify all providers inherit from BaseProvider."""

    @pytest.mark.parametrize("cls", ALL_PROVIDERS, ids=lambda c: c.__name__)
    def test_is_subclass_of_base(self, cls):
        assert issubclass(cls, BaseProvider)


class TestProviderInterface:
    """Verify all providers expose the required interface methods."""

    #: Methods the engine calls ACROSS the provider seam. Each one has a
    #: named production caller — if you add a row here, name the caller.
    #: (`get_model_profile` was here until ADR 0012 refactor (b): it returned
    #: the retiring `ModelProfile` vocabulary and had zero callers.)
    REQUIRED_METHODS = [
        "chat",                  # engine/chat.py:324,761,816,1203
        "oneshot",               # server/routes/oneshot.py:648 — abstract on base
        "list_models",           # engine/provider_ops.py:257,332
        "get_facts_for_model",   # engine/chat.py:600
        "get_capabilities",      # no caller by design — ADR 0012 Q0e, see docstring
    ]

    #: Shared base-class implementation, NOT interface. Zero callers outside
    #: `providers/`. Pinned so a provider that reimplements the hierarchy
    #: still inherits them, but kept separate so nobody mistakes an internal
    #: helper for a contract the engine depends on.
    SHARED_HELPERS = [
        "_get_generation_params",
        "_get_max_tokens",
        "_format_error",
        "_log_error_traceback",
        "_parse_usage",
    ]

    @pytest.mark.parametrize("cls", ALL_PROVIDERS, ids=lambda c: c.__name__)
    @pytest.mark.parametrize("method", REQUIRED_METHODS)
    def test_has_seam_method(self, cls, method):
        assert hasattr(cls, method), f"{cls.__name__} missing {method}"
        assert callable(getattr(cls, method))

    @pytest.mark.parametrize("cls", ALL_PROVIDERS, ids=lambda c: c.__name__)
    @pytest.mark.parametrize("method", SHARED_HELPERS)
    def test_has_shared_helper(self, cls, method):
        assert hasattr(cls, method), f"{cls.__name__} missing {method}"
        assert callable(getattr(cls, method))

    @pytest.mark.parametrize("method", REQUIRED_METHODS + SHARED_HELPERS)
    def test_no_resurrected_dead_method(self, method):
        """`chat_sync_simple`, `validate_config` and `needs_tool` were deleted
        2026-09-20 after a full-history search found no caller. If one comes
        back, it needs a caller and a row — not just an implementation."""
        assert method not in ("chat_sync_simple", "validate_config", "needs_tool")


class TestTheTwoAccessors:
    """Two records, two accessors (ADR 0012 section 2 Q0e).

    RETARGETED from `TestGetCapabilitiesForModel`. Every test here used to
    assert `get_capabilities_for_model(m) is provider.capabilities` -- a
    PASSTHROUGH, which was the right contract while tool calling lived on
    the provider record. It does not any more: `get_capabilities()` answers
    for the endpoint and takes no model, `get_facts_for_model()` answers for
    the model and consults the shipped table. "Returns self.capabilities
    unchanged for any model" is not a claim that can be made about either.
    """

    def test_endpoint_accessor_returns_the_provider_record(self):
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        assert provider.get_capabilities() == provider.capabilities

    def test_openai_native_resolves_prompt_based_models_per_model(self):
        """The benchmark table, through the new accessor."""
        with patch("ppxai.engine.providers.openai_native.OpenAI"):
            provider = OpenAINativeProvider(api_key="test")

        assert provider.get_facts_for_model("gpt-5.2").tool_mode != "prompt_based"
        assert provider.get_facts_for_model("o4-mini").tool_mode == "prompt_based"
        assert (
            provider.get_facts_for_model("gpt-4.1-mini").tool_mode == "prompt_based"
        )

    def test_perplexity_splits_endpoint_from_model(self):
        """`sonar` is not tool-capable, but the ENDPOINT still searches."""
        with patch("ppxai.engine.providers.base.OpenAI"):
            provider = PerplexityProvider(
                api_key="test",
                base_url="https://api.perplexity.ai",
            )
        assert provider.get_capabilities().web_search is True
        assert provider.get_facts_for_model("sonar").tool_mode == "prompt_based"
        assert provider.get_facts_for_model("sonar-pro").tool_mode != "prompt_based"

    def test_gemini_splits_endpoint_from_model(self):
        with patch("ppxai.engine.providers.gemini.genai") as mock_genai:
            mock_genai.Client.return_value = MagicMock()
            provider = GeminiProvider(api_key="test")
        assert provider.get_capabilities().web_search is True
        facts = provider.get_facts_for_model("gemini-2.5-flash")
        assert facts.tool_mode == "native"
        assert facts.wire_protocol == "generate_content"


class TestBaseUrlOptional:
    """Test that base_url=None skips OpenAI client creation."""

    def test_base_url_none_skips_client(self):
        """When base_url=None, BaseProvider.__init__ skips client creation."""
        with patch("ppxai.engine.providers.openai_native.OpenAI") as mock_openai:
            provider = OpenAINativeProvider(api_key="test")
        # OpenAI client should be created by the subclass, not by BaseProvider
        # BaseProvider with base_url=None returns early, so self.client is set
        # by the subclass's own __init__
        assert hasattr(provider, "client")

    def test_base_url_provided_creates_client(self):
        """When base_url is provided, BaseProvider creates OpenAI client."""
        with patch("ppxai.engine.providers.base.OpenAI") as mock_openai:
            provider = OpenAICompatibleProvider(
                api_key="test",
                base_url="http://localhost:8000/v1",
            )
        mock_openai.assert_called_once()
        assert hasattr(provider, "client")
