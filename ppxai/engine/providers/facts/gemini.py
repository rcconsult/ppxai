"""Facts for `GeminiProvider` (ADR 0016 §3). No SDK import."""

from ...model_facts import ModelFacts
from ...types import ProviderCapabilities
from ._record import ProviderFacts

FACTS = ProviderFacts(
    #: Stands in when a caller builds a config with no target model. Every
    #: Gemini model this provider reaches is native + generate_content, so
    #: any row answers correctly; naming one keeps the resolution honest
    #: rather than special-casing "no model" into a hardcoded True. It is the
    #: shipped default model, so its `restricted_params` also apply; it was
    #: `gemini-2.5-pro` until the 2.5 line's 2026-10-16 sunset.
    default_model_for_facts="gemini-3.8-flash",
    #: An UNLISTED Gemini model still speaks `generate_content` — this
    #: provider has no other wire. The global floor says `chat_completions`,
    #: which is safe everywhere else and simply wrong here, so Gemini
    #: supplies its own complete floor (ADR 0012 §2 Q0e).
    #:
    #: `tool_mode` stays CONSERVATIVE: an unmeasured model is assumed not
    #: tool-capable regardless of provider. The wire is a fact about the
    #: endpoint's protocol; tool support is a fact about the model, and only
    #: the first is knowable without measuring.
    #:
    #: `restricted_params` is the other half of the floor (2026-10-08): an
    #: unlisted Gemini model is a NEWER one, and Google's deprecation notice
    #: says the upcoming models reject temperature/top_p/top_k with 400
    #: INVALID_ARGUMENT (fixed defaults since 3.6 Flash). Restricting them on
    #: the floor keeps a model the seed table has not caught up with
    #: working, at no cost — the values had no effect since 3.6.
    unmeasured_facts=ModelFacts(
        wire_protocol="generate_content",
        restricted_params=("temperature", "top_p", "top_k"),
    ),
    default_capabilities=ProviderCapabilities(
        web_search=True,   # Via Google Search Grounding
        web_fetch=True,    # Can answer about URLs via grounding
        weather=True,      # Can answer weather via grounding
        citations=True,    # Grounding provides citations
        streaming=True,
    ),
)
