"""Per-model capabilities must reach the provider SEND paths (plan I1).

`BaseProvider.get_capabilities_for_model(model)` is the hook that lets a
provider mark individual models prompt-based. Before this fence only
`chat.py:686` consulted it: all four provider send paths read the static
`self.capabilities` instead, so `OpenAINativeProvider`'s benchmark-backed
`PROMPT_BASED_MODEL_PREFIXES` override resolved False and the send path
shipped native tools anyway.

Two layers of protection, deliberately:

* a **behavioural** check that the resolved capability differs per model
  and that the send path acts on it, and
* a **source** check that no send path reads `self.capabilities.
  native_tool_calling` again. The behavioural test alone would not catch
  a NEW provider or a NEW send path reintroducing the stale read.
"""

from __future__ import annotations

import inspect
import re
from pathlib import Path

import pytest

from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.providers.openai_native import (
    PROMPT_BASED_MODEL_PREFIXES,
    OpenAINativeProvider,
)

PROVIDERS_DIR = Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "providers"


class TestTheHookResolvesPerModel:
    """The override itself — unchanged behaviour, pinned so I2/I5 can't
    silently drop it while reshaping the table."""

    def test_prompt_based_models_resolve_false(self):
        p = OpenAINativeProvider(api_key="sk-test")
        for prefix in PROMPT_BASED_MODEL_PREFIXES:
            caps = p.get_capabilities_for_model(prefix)
            assert caps.native_tool_calling is False, (
                f"{prefix} is in PROMPT_BASED_MODEL_PREFIXES but resolved "
                "native_tool_calling=True"
            )

    def test_other_models_resolve_true(self):
        p = OpenAINativeProvider(api_key="sk-test")
        assert p.get_capabilities_for_model("gpt-5.4").native_tool_calling is True

    def test_the_static_attribute_still_disagrees(self):
        """The whole point: `self.capabilities` is NOT per-model.

        If this ever stops disagreeing, the send-path tests below become
        vacuous — they would pass whichever attribute the code read.
        """
        p = OpenAINativeProvider(api_key="sk-test")
        assert p.capabilities.native_tool_calling is True
        assert p.get_capabilities_for_model("o4-mini").native_tool_calling is False


class TestSendPathsConsultTheHook:
    """Source-level: the four sites that decide whether to attach tools."""

    #: (module, method) pairs that gate tool attachment on capability.
    SEND_PATHS = [
        ("openai_native.py", "_chat_completions_api"),
        ("openai_native.py", "_chat_responses_api"),
        ("openai_compat.py", "chat"),
        ("gemini.py", "_build_config"),
    ]

    def test_no_send_path_reads_the_static_attribute(self):
        """Repo-wide: `self.capabilities.native_tool_calling` is banned.

        Read the provider's own hook instead. Kept as a path scan rather
        than a per-method check so a NEW provider or a NEW send path is
        covered the day it is written.
        """
        pattern = re.compile(r"self\.capabilities\.native_tool_calling")
        offenders = []
        for path in PROVIDERS_DIR.glob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(path.name)
        assert offenders == [], (
            f"{offenders} read self.capabilities.native_tool_calling, which "
            "ignores the per-model override. Use "
            "self.get_capabilities_for_model(model).native_tool_calling."
        )

    @pytest.mark.parametrize("module,method", SEND_PATHS)
    def test_each_send_path_uses_the_hook(self, module, method):
        src = (PROVIDERS_DIR / module).read_text(encoding="utf-8")
        # Locate the method body: from its def to the next same-level def.
        m = re.search(rf"\n    (?:async )?def {re.escape(method)}\(", src)
        assert m, f"{module}::{method} not found — did it get renamed?"
        rest = src[m.end():]
        nxt = re.search(r"\n    (?:async )?def ", rest)
        body = rest[: nxt.start()] if nxt else rest
        assert "get_capabilities_for_model(" in body, (
            f"{module}::{method} decides tool attachment but never calls "
            "get_capabilities_for_model()"
        )


class TestGeminiThreadsModel:
    """Gemini's `_build_config` had no `model` parameter, so it could not
    consult the hook without a signature change. Pin the plumbing."""

    def test_build_config_accepts_model(self):
        from ppxai.engine.providers.gemini import GeminiProvider

        sig = inspect.signature(GeminiProvider._build_config)
        assert "model" in sig.parameters

    def test_every_build_config_caller_passes_model(self):
        """A caller that omits `model` silently falls back to the static
        capabilities — the exact bug, reintroduced one call site at a time."""
        src = (PROVIDERS_DIR / "gemini.py").read_text(encoding="utf-8")
        calls = [
            m.start() for m in re.finditer(r"self\._build_config\(", src)
        ]
        assert calls, "no _build_config callers found — test is stale"
        for pos in calls:
            # The argument list ends at the first ')' at paren-depth 0.
            depth, i = 0, src.index("(", pos)
            for i in range(i, len(src)):
                if src[i] == "(":
                    depth += 1
                elif src[i] == ")":
                    depth -= 1
                    if depth == 0:
                        break
            args = src[pos:i]
            line = src[:pos].count("\n") + 1
            assert "model=" in args, (
                f"gemini.py:{line} calls _build_config() without model=, so "
                "it cannot honour a per-model capability override"
            )


class TestHookContractOnBase:
    def test_base_declares_the_hook(self):
        assert hasattr(BaseProvider, "get_capabilities_for_model")

    def test_base_default_is_a_passthrough(self):
        """Providers without a per-model table must behave exactly as before
        — I1 is a wiring change, not a behaviour change, for them."""

        class _Dummy(BaseProvider):
            async def chat(self, *a, **k):  # pragma: no cover - unused
                yield None

            def oneshot(self, *a, **k):  # pragma: no cover - unused
                return {}

        d = _Dummy(api_key="k")
        assert d.get_capabilities_for_model("anything") is d.capabilities
