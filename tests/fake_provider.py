"""A provider that answers without the network, for tests that need a reply.

The conftest network guard fails any test that reaches a real host. Tests
that drive a real chat or oneshot path -- and so need SOME provider to
answer -- take the `fake_providers` fixture instead, which installs
`FakeChatProvider` under every registered provider name. The engine, the
server routes and the usage accounting all run for real; only the wire call
is replaced.

Replies are deterministic: the text is always "pong", and token counts are
derived from the request, so two calls accumulate and a longer prompt costs
more -- enough for usage tests to assert real arithmetic.
"""

from dataclasses import dataclass, field

from ppxai.config import PROVIDERS
from ppxai.engine import provider_ops, providers
from ppxai.engine.providers.base import BaseProvider
from ppxai.engine.types import Event, EventType, UsageStats

REPLY = "pong"


def _prompt_tokens(messages) -> int:
    chars = sum(len(str(getattr(m, "content", m) or "")) for m in messages)
    return max(1, chars // 4)


class FakeChatProvider(BaseProvider):
    """BaseProvider with the two wire methods answered locally.

    Everything else -- capabilities, model facts, generation params -- is
    the real BaseProvider logic over the real provider config, so a test sees
    the same facts it would with the real class. `calls` records each
    request as (kind, model).
    """

    def __init__(self, api_key="test-key", base_url=None, **kwargs):
        # base_url=None: BaseProvider then builds no OpenAI client at all.
        super().__init__(api_key=api_key, base_url=None, **kwargs)
        self.calls: list[tuple[str, str]] = []

    async def chat(self, messages, model, stream=False, tools=None):
        self.calls.append(("chat", model))
        prompt = _prompt_tokens(messages)
        usage = UsageStats(prompt_tokens=prompt, completion_tokens=1,
                           total_tokens=prompt + 1)
        yield Event(EventType.STREAM_START, None)
        if stream:
            yield Event(EventType.STREAM_CHUNK, REPLY)
        yield Event(EventType.STREAM_END, REPLY, {"usage": usage})

    def oneshot(self, prompt, model, system=None, response_format=None,
                max_tokens=None, temperature=None):
        self.calls.append(("oneshot", model))
        tokens = max(1, len(prompt) // 4)
        return {
            "content": REPLY,
            "finish_reason": "stop",
            "model": model,
            "usage": {"prompt_tokens": tokens, "completion_tokens": 1,
                      "total_tokens": tokens + 1},
        }


@dataclass
class FakeProviders:
    """What the fixture hands the test: the instances it created, in order."""
    created: list[FakeChatProvider] = field(default_factory=list)

    @property
    def calls(self) -> list[tuple[str, str]]:
        return [c for p in self.created for c in p.calls]


def install(monkeypatch) -> FakeProviders:
    """Route every provider construction to FakeChatProvider.

    Covers both construction paths: `create_provider()` (every registered
    name, via the registry it reads) and the OpenAI-compatible fallback
    `set_provider` uses for a name the registry does not know. Every
    configured provider's key is replaced with a placeholder: `set_provider`
    refuses a provider without one, and a real key must not be in reach of
    anything that bypasses the fake -- it would fail auth, not bill.
    """
    record = FakeProviders()

    class _Recorded(FakeChatProvider):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            record.created.append(self)

    for name in list(providers._providers):
        monkeypatch.setitem(providers._providers, name, _Recorded)
    monkeypatch.setattr(provider_ops, "OpenAICompatibleProvider", _Recorded)

    for cfg in PROVIDERS.values():
        if cfg.get("api_key_env"):
            monkeypatch.setenv(cfg["api_key_env"], "test-key")
    return record
