"""The wire fact the Perplexity search backend needs.

`engine/search/perplexity.py` picks its wire from this table for the
configured `tools.web_search.perplexity_model`. Until ADR 0015 removed
Perplexity as a chat provider, the table also carried the chat provider's
gateway rows (`openai/*`, `anthropic/*`, `google/*`, `xai/*`) and its
Sonar tool-calling measurements; only the search backend's row is left.
Data only: nothing here imports a provider. This module lives under
`ppxai/engine/search/` and is fenced by
`tests/test_search_layer_imports_no_providers.py`.
"""

from dataclasses import replace

from ..model_facts import shipped_facts_for_model

#: Sonar's namespaced ids are served on the OpenAI **Responses** wire at
#: `https://api.perplexity.ai/v1/responses` (measured 2026-08-31;
#: `perplexity/sonar` is the only Sonar id served there). The bare ids
#: (`sonar`, `sonar-pro`, ...) were chat-completions only and that endpoint
#: retired on 2026-09-27; they resolve through the shipped rows, not this
#: table.
SEARCH_WIRE_GLOBS = ("perplexity/*",)

#: A budget must be present: the Responses handler sends
#: `max_output_tokens` only when it is non-zero. An operator
#: `facts.max_tokens` override does not apply here, since this table is not
#: a provider's.
SEARCH_MAX_TOKENS = 4096

SEARCH_MODEL_FACTS = {
    glob: replace(
        shipped_facts_for_model(glob.rstrip("*")),
        wire_protocol="responses",
        max_tokens=SEARCH_MAX_TOKENS,
    )
    for glob in SEARCH_WIRE_GLOBS
}
