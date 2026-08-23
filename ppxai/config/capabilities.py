"""Per-model capability resolution (plan I2).

`ProviderCapabilities` describes what an endpoint can do — native tool
calling, web search, streaming. It has always been declared per PROVIDER,
which stopped being true of every provider we ship: Perplexity serves
`sonar-pro` (native tool calls) beside `sonar` (HTTP 400 on any tools
array), and `openai_compat` fronts arbitrary vLLM/NIM fleets by design.

This module is the single accessor. Resolution order, narrowest wins::

    1. providers.<p>.models.<m>.capabilities   config   (operator, per model)
    2. provider code: per-model table                   (shipped, per model)
    3. providers.<p>.capabilities              config   (operator, per provider)
    4. provider code: default_capabilities              (shipped, per provider)

Note layers 2 and 3: a per-MODEL statement outranks a per-PROVIDER one
regardless of which side it came from. Specificity wins before authorship
does. The plan originally listed both config layers above both code
layers; that was wrong, and the user's own config proves why — it carries
a provider-wide ``native_tool_calling: true`` for OpenAI (a restatement of
the default, present since long before per-model tables existed), which
under the flat ordering silently re-enabled native tools for ``o4-mini``
and cancelled the benchmark-backed table. An operator who wants that must
say so against the model.

Layers 3 and 4 stay inside the provider — `get_capabilities_for_model()`
is still the provider-facing method, and a provider with no per-model
table behaves exactly as before. This module supplies the two config
layers above them, so an operator can correct a stale shipped table
without waiting for a release.

**Why config may override a capability at all.** A capability is a
*statement about the endpoint*, not a privilege grant: getting it wrong
degrades a feature (a tool call is not attempted) rather than widening a
security boundary. That is the opposite of `TIERS` in
`engine/task_authorizer.py`, which is deliberately compiled precisely
because a JSON typo there would be a privilege escalation.

**Reading the raw config file is deliberate.** `load_config()` runs
per-model config through `_convert_models_format`, which keeps only
``id``/``name``/``description`` — a per-model ``capabilities`` block is
silently discarded (verified 2026-08-15). `get_tool_calling_config` in
`providers.py` already reads the raw file for exactly this reason; this
module follows that precedent rather than widening the converter, which
would change the shape every existing model-config reader sees.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from ..engine.types import ProviderCapabilities
from .loader import _load_json_config, find_config_file

#: Fields an operator may state per provider or per model. Anything else in
#: a `capabilities` block is ignored rather than crashing the load — a
#: config typo must not take the app down, and an unknown key is far more
#: likely a typo or a future field than an instruction we can honour.
_CAPABILITY_FIELDS = (
    "web_search",
    "web_fetch",
    "weather",
    "citations",
    "streaming",
    "native_tool_calling",
)


def _raw_provider_block(provider: str) -> Dict[str, Any]:
    """`providers.<provider>` straight from the config FILE.

    Not from `load_config()` — see the module docstring: the converter
    strips per-model keys this function exists to read.
    """
    try:
        path = find_config_file()
        if not path:
            return {}
        cfg = _load_json_config(path) or {}
    except Exception:  # noqa: BLE001 — unreadable config must not break chat
        return {}
    providers = cfg.get("providers")
    if not isinstance(providers, dict):
        return {}
    block = providers.get(provider)
    return block if isinstance(block, dict) else {}


def _clean(block: Any) -> Dict[str, bool]:
    """The recognised, boolean-valued entries of a `capabilities` block.

    Drops `__comment*` documentation keys (the convention used throughout
    `ppxai-config.example.json`) and anything not in `_CAPABILITY_FIELDS`.
    Values are coerced to bool so `"true"` in hand-edited JSON behaves.
    """
    if not isinstance(block, dict):
        return {}
    out: Dict[str, bool] = {}
    for key in _CAPABILITY_FIELDS:
        if key not in block:
            continue
        raw = block[key]
        if isinstance(raw, bool):
            out[key] = raw
        elif isinstance(raw, str):
            out[key] = raw.strip().lower() in ("true", "1", "yes", "on")
        else:
            out[key] = bool(raw)
    return out


def config_provider_overrides(provider: str) -> Dict[str, bool]:
    """Operator statements made against the PROVIDER as a whole (layer 3)."""
    return _clean(_raw_provider_block(provider).get("capabilities"))


def config_model_overrides(provider: str, model: Optional[str]) -> Dict[str, bool]:
    """Operator statements made against ONE model (layer 1)."""
    if not model:
        return {}
    models = _raw_provider_block(provider).get("models")
    if not isinstance(models, dict):
        return {}
    block = models.get(model)
    return _clean(block.get("capabilities")) if isinstance(block, dict) else {}


def config_capability_overrides(
    provider: str, model: Optional[str] = None
) -> Dict[str, bool]:
    """Every operator statement that applies, model-level winning.

    Kept as the combined view for callers that only need "what did the
    operator say"; `apply_capability_overrides` uses the two halves
    separately because they sit on OPPOSITE sides of the shipped per-model
    table.
    """
    merged = config_provider_overrides(provider)
    merged.update(config_model_overrides(provider, model))
    return merged


def apply_capability_overrides(
    base: ProviderCapabilities, provider: str, model: Optional[str] = None
) -> ProviderCapabilities:
    """`base` with any operator overrides applied.

    `base` is what the provider itself resolved — which already folded the
    operator's provider-level statement in via `default_capabilities`, and
    then applied its own per-model table on top. So only the per-MODEL
    config layer is applied here: a provider-wide statement must not
    outrank a model-specific one (see the module docstring).

    Returns `base` unchanged when nothing is stated against the model, so
    this is a no-op for every existing install.
    """
    overrides = config_model_overrides(provider, model)
    if not overrides:
        return base
    return ProviderCapabilities(
        **{
            field: overrides.get(field, getattr(base, field))
            for field in _CAPABILITY_FIELDS
            if hasattr(base, field)
        }
    )
