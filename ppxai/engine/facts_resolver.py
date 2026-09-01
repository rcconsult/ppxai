"""Resolving a provider NAME to the facts that will serve it.

Split from `model_facts` to make the dependency point one way (step 3 of the
lazy-import cleanup). That module is the DATA — `ModelFacts`,
`SHIPPED_MODEL_FACTS`, `shipped_facts_for_model` — which `providers` imports.
This module is the RESOLVER, which imports `providers`. Both lived in one
file, so the file depended on `providers` and `providers` depended on it; the
cycle was survivable only because these functions imported lazily.

ADR 0012 §2 already describes facts as the vocabulary providers consume. This
makes the module graph say the same thing.

**Composes both layers, so neither may import it** — a `from .facts_resolver
import ...` in `model_facts` or `providers` restores the cycle.
"""

from dataclasses import asdict, dataclass
from typing import Any

from ..config.facts_config import apply_provider_overrides, resolve_model_facts
from .model_facts import ModelFacts, can_drive_a_tool_loop, shipped_facts_for_model
from .providers.openai_compat import OpenAICompatibleProvider


def provider_class_for(provider: str):
    """The class that will actually serve `provider`.

    Thin wrapper over :attr:`FactsResolver.provider_class` — kept because it
    has callers and reads well at a call site that needs only the class.
    """
    return FactsResolver(provider).provider_class


def capabilities_without_an_instance(provider: str):
    """Resolve the ENDPOINT record from the provider CLASS.

    Thin wrapper over :meth:`FactsResolver.capabilities`.
    """
    return FactsResolver(provider).capabilities()


def facts_without_an_instance(provider: str, model: str) -> ModelFacts:
    """Resolve `model` on `provider` from the provider CLASS.

    Thin wrapper over :meth:`FactsResolver.facts`. The one resolution path
    for callers with no provider instance — the admission guard (no API key
    at admission time), the oneshot enrichment gate, `/doctor`, `/provider`.
    Each used to spell out the same four-line incantation; four copies of one
    sequence is how a fifth caller gets a rung wrong, which had already
    happened twice when this was written.
    """
    return FactsResolver(provider).facts(model)


@dataclass(frozen=True)
class FactsResolver:
    """Everything resolvable about a provider from its NAME alone.

    Constructed from a provider key; resolves the class once (by the one
    fallback rule), then answers the endpoint record, any model's facts, and
    whether a model can drive a tool loop.

    **Why a type rather than three functions.** `provider_class_for`,
    `capabilities_without_an_instance` and `facts_without_an_instance` were
    function-shaped carving around one missing abstraction: each re-derived
    the class, and callers that needed two answers resolved it twice. Worse,
    the "unknown name means `OpenAICompatibleProvider`" rule had grown FIVE
    spellings across the tree — `provider_class_for`, `provider_ops`'s
    construction fallback, `task_authorizer`'s `get_provider_class(...) is
    None` early return, and `facts_config`'s fallback to a bare
    `ProviderCapabilities()`. That last one agrees with the real answer only
    because `ProviderCapabilities()` and
    `OpenAICompatibleProvider.default_capabilities` happen to be equal today;
    change either and `/doctor` starts scaffolding a record the engine does
    not use, silently.

    One type, one rule, one resolution. The three functions remain as thin
    wrappers — they have callers, and a resolver whose adoption requires
    touching every call site in one commit is a worse trade than one that
    can be adopted where it helps.
    """

    provider: str

    @property
    def provider_class(self):
        """The class that will actually serve this provider.

        `get_provider_class()` alone is NOT the answer: it returns `None`
        for every openai_compat-TYPE provider — openrouter, nvidia, a vLLM
        box, an Ollama host — because those are configured by name, not
        registered. A caller that stops at `None` disagrees with the
        deployment about what a provider is, which was a live defect on the
        oneshot enrichment gate.
        """

        # Lazy: tests patch `providers.get_provider_class` on the SOURCE
        # module, and a module-scope binding here would not see the patch.
        from .providers import get_provider_class

        try:
            cls = get_provider_class(self.provider)
        except Exception:  # noqa: BLE001
            cls = None
        return cls if cls is not None else OpenAICompatibleProvider

    @property
    def is_registered(self) -> bool:
        """Whether this name is a REGISTERED provider, not a type-based one.

        The honest form of `get_provider_class(p) is None`. Callers wanting
        "do we know this provider at all?" should ask this rather than
        re-deriving it — and should notice that the answer being `False`
        does not mean unserviceable, only unregistered.
        """

        # Lazy: tests patch `providers.get_provider_class` on the SOURCE
        # module, and a module-scope binding here would not see the patch.
        from .providers import get_provider_class

        try:
            return get_provider_class(self.provider) is not None
        except Exception:  # noqa: BLE001
            return False

    def capabilities(self):
        """The ENDPOINT record, with operator overrides applied."""

        return apply_provider_overrides(
            self.provider_class.default_capabilities, self.provider
        )

    def facts(self, model: str) -> ModelFacts:
        """The MODEL record: shipped table, provider floor, operator config."""

        cls = self.provider_class
        table = getattr(cls, "shipped_model_facts", {}) or {}
        floor = getattr(cls, "unmeasured_facts", None)
        return resolve_model_facts(
            shipped_facts_for_model(model, table, floor), self.provider, model
        )

    def can_drive_a_tool_loop(self, model: str) -> bool:
        """Whether `model` can run a tool loop at all — any strategy."""
        return can_drive_a_tool_loop(self.facts(model))


def complete_record_for(
    provider: str, model: str | None = None
) -> dict[str, Any]:
    """The full `facts` record `/doctor` writes to fix a partial block.

    Q0e puts the verbosity burden on the tool, not the operator: with two
    records and 17 fields between them, hand-writing a complete block for
    every model is exactly the burden that makes people write partial ones.
    This generates it.

    Every field carries the value it currently resolves to, so writing the
    result into the config is **behaviour-preserving by construction** — it
    makes the implicit explicit and nothing else. Pass a `model` for a
    `ModelFacts` record; omit it for the provider's `ProviderCapabilities`.
    """


    # ADR 0012 refactor (a): ONE resolver, so the record `/doctor` offers to
    # paste is the record the engine will resolve. This used to fall back to a
    # bare `ProviderCapabilities()` for any name `get_provider_class` did not
    # know — which agreed with the real answer only because that default and
    # `OpenAICompatibleProvider.default_capabilities` happen to be equal.
    # Change either and /doctor would have started scaffolding a record the
    # engine does not use, silently and for every openai_compat provider.
    resolver = FactsResolver(provider)

    if model is None:
        return asdict(resolver.capabilities())

    record = asdict(resolver.facts(model))
    if isinstance(record.get("restricted_params"), tuple):
        record["restricted_params"] = list(record["restricted_params"])
    return record
