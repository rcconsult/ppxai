"""Per-model facts must reach the provider SEND paths (plan I1, ADR 0012).

`BaseProvider.get_facts_for_model(model)` is the hook that lets a provider
mark individual models prompt-based. Before this fence only `chat.py`
consulted it: all four provider send paths read the static
`self.capabilities` instead, so `OpenAINativeProvider`'s benchmark-backed
`PROMPT_BASED_MODEL_PREFIXES` override resolved False and the send path
shipped native tools anyway.

Retargeted for ADR 0012 §2 Q0e: the accessor is now `get_facts_for_model`
and the answer is `tool_mode`, not a boolean. The fence itself is
unchanged in kind — it is the one that catches a send path reading a
static attribute instead of resolving per model — so it is retargeted
rather than dropped.

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

    def test_prompt_based_models_resolve_prompt_based(self):
        p = OpenAINativeProvider(api_key="sk-test")
        for prefix in PROMPT_BASED_MODEL_PREFIXES:
            facts = p.get_facts_for_model(prefix)
            assert facts.tool_mode == "prompt_based", (
                f"{prefix} is in PROMPT_BASED_MODEL_PREFIXES but resolved "
                f"tool_mode={facts.tool_mode}"
            )

    def test_other_models_resolve_tool_capable(self):
        p = OpenAINativeProvider(api_key="sk-test")
        assert p.get_facts_for_model("gpt-5.4").tool_mode != "prompt_based"

    def test_resolution_differs_per_model(self):
        """The whole point: the answer is NOT one value for the provider.

        If two models ever stop disagreeing, the send-path tests below
        become vacuous — they would pass whichever value the code read.

        Under ADR 0012 §2 Q0e this can no longer be phrased as "the static
        attribute disagrees with the hook": tool mode was removed from
        `ProviderCapabilities` entirely, so there is no provider-level
        value left to disagree with. That is a stronger guarantee than the
        one this test originally asserted — the stale read is now a
        `AttributeError`, not a wrong answer — and the per-model
        disagreement is what remains to pin.
        """
        p = OpenAINativeProvider(api_key="sk-test")
        assert p.get_facts_for_model("gpt-5.4").tool_mode != "prompt_based"
        assert p.get_facts_for_model("o4-mini").tool_mode == "prompt_based"

    def test_tool_mode_is_not_reachable_from_the_provider_record(self):
        """Q0g removed the boolean; a stale read must fail loudly."""
        p = OpenAINativeProvider(api_key="sk-test")
        assert not hasattr(p.capabilities, "native_tool_calling")


class TestSendPathsConsultTheHook:
    """Source-level: the four sites that decide whether to attach tools."""

    #: (module, method) pairs that gate tool attachment on capability.
    #: ADR 0012 W2 moved the Responses send path out of the provider and into
    #: `wire/responses.py`; the fence follows the code, because a send path
    #: that leaves this list stops being guarded the day it moves.
    SEND_PATHS = [
        ("openai_native.py", "_chat_completions_api"),
        ("wire/responses.py", "build_request"),
        ("openai_compat.py", "chat"),
        ("gemini.py", "_build_config"),
    ]

    def test_no_send_path_reads_the_static_attribute(self):
        """Repo-wide: `self.capabilities.native_tool_calling` is banned.

        Read the provider's own hook instead. Kept as a path scan rather
        than a per-method check so a NEW provider or a NEW send path is
        covered the day it is written.
        """
        # rglob, not glob: ADR 0012 W2 put send-path code in the `wire/`
        # subpackage, and a top-level-only scan would have stopped seeing it
        # exactly when it moved.
        pattern = re.compile(r"(self|ctx)\.capabilities\.(native_tool_calling|tool_mode)")
        offenders = []
        for path in PROVIDERS_DIR.rglob("*.py"):
            if pattern.search(path.read_text(encoding="utf-8")):
                offenders.append(str(path.relative_to(PROVIDERS_DIR)))
        assert offenders == [], (
            f"{offenders} read self.capabilities.native_tool_calling, which "
            "ignores the per-model override. Use "
            'self.get_facts_for_model(model).tool_mode != "prompt_based".'
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
        assert "get_facts_for_model(" in body, (
            f"{module}::{method} decides tool attachment but never calls "
            "get_facts_for_model()"
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
        assert hasattr(BaseProvider, "get_facts_for_model")

    def test_base_declares_the_endpoint_accessor_separately(self):
        """Two records, two accessors (ADR 0012 §2 Q0e).

        `get_capabilities()` takes NO model, because every field on that
        record is a fact about the service. The signature is the guarantee:
        an endpoint question cannot accidentally be asked per model.
        """
        import inspect

        assert hasattr(BaseProvider, "get_capabilities")
        params = inspect.signature(BaseProvider.get_capabilities).parameters
        assert list(params) == ["self"], (
            "get_capabilities() grew a model parameter — the provider record "
            "is per-ENDPOINT, and a model argument reintroduces exactly the "
            "two-levels-of-one-field shape ADR 0012 removed"
        )

    def test_base_default_falls_to_the_shipped_table(self):
        """A provider with no table of its own resolves from the shipped one.

        RETARGETED for ADR 0012 §2 Q0e. This test used to assert the default
        was `self.capabilities` — a passthrough — because tool mode lived on
        the provider record. It no longer does, so "passthrough" has no
        meaning here: the base default now consults the shipped per-model
        table, and a model nobody has measured lands on the conservative
        floor rather than inheriting a provider-wide value. That inheritance
        is precisely what let a provider-level statement speak for `sonar`.
        """
        from ppxai.engine.model_facts import shipped_facts_for_model

        class _Dummy(BaseProvider):
            async def chat(self, *a, **k):  # pragma: no cover - unused
                yield None

            def oneshot(self, *a, **k):  # pragma: no cover - unused
                return {}

        d = _Dummy(api_key="k")
        assert d.get_facts_for_model("gpt-5.2") == shipped_facts_for_model("gpt-5.2")
        assert d.get_facts_for_model("nobody-measured-this").tool_mode == (
            "prompt_based"
        )
