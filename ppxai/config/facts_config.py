"""Operator config for the two fact records (ADR 0012 §2 Q0e).

The unified successor to the two config readers this replaces:
`capabilities.py` (the `capabilities` block) and `providers.py::
get_tool_calling_config` (the `tool_calling` block).

**One block name, two record types, disjoint fields.** An operator writes
`facts` in exactly two places, and which record it means is decided by
*where it sits*, not by arbitration::

    providers.<p>.facts                  → ProviderCapabilities  (endpoint)
    providers.<p>.models.<m>.facts       → ModelFacts            (model)

Because the field sets are disjoint (`PROVIDER_FACT_FIELDS` vs
`FACT_FIELDS`), a field stated in the wrong place is not a conflict to
resolve — it is simply not a field of that record, and `/doctor` reports it
as misplaced. This is what collapsed the five-rung precedence ladder to two
independent lookups: there is no level at which two statements about one
field can meet.

**Clean break — the resolver reads ONE vocabulary** (Q0c, following ADR
0010's precedent). The legacy `capabilities` and `tool_calling` blocks are
**not** read. Accepting old keys at resolution time would be a permanent
dual-read — exactly what a clean break exists to avoid, and it would leave
two spellings of every fact alive indefinitely.

Because a moved key is invisible to every accessor, `/doctor` carries the
migration: :func:`legacy_blocks_in_config` reads the config FILE, reports
every legacy key with its replacement, and drives the rewrite. That pairing
— break plus file scan — is the lesson recorded in
`docs/lessons/clean-break-config-moves-need-a-file-scan.md`, learned when
ADR 0010 moved keys with no dual-read and nothing could see the stale ones.

⚠️ **Migration is mandatory, not advisory.** Measured 2026-08-30:
`openrouter` and `ollama` in the shipped example config hold native tool
calling on **solely** via `capabilities.native_tool_calling: true`, with no
`tool_calling` block at all. Under a clean break an unmigrated config
resolves those models to the conservative floor (`prompt_based`). The
example config ships migrated, and `/doctor` reports any file still carrying
the old spelling — but a deployment that never runs `/doctor` will degrade
rather than fail loudly. That is the accepted cost of the break.

**Reading the raw config file is deliberate**, inherited from both
predecessors: `load_config()`'s `_convert_models_format` keeps only
id/name/description, so a per-model block is silently discarded unless the
file is read directly. The whole provider block is read once per resolution
and both lookups are served from it.
"""

from __future__ import annotations

from dataclasses import fields as dataclass_fields
from typing import Any, Dict, List, Optional

from ..engine.model_facts import (
    FACT_FIELDS,
    LEGACY_KEY_TRANSLATIONS,
    PROVIDER_FACT_FIELDS,
    ModelFacts,
    apply_overrides,
)
from ..engine.types import ProviderCapabilities
from .loader import _load_json_config, find_config_file

#: The one block the resolver reads. Legacy names are reported by `/doctor`,
#: never resolved.
FACTS_BLOCK = "facts"

#: Legacy blocks `/doctor` scans for. Read from the FILE, never resolved.
LEGACY_BLOCKS = ("capabilities", "tool_calling")


def raw_provider_block(provider: str) -> Dict[str, Any]:
    """`providers.<provider>` straight from the config FILE.

    Public because a caller resolving both records should read the file
    **once** and pass the block to both lookups, rather than re-parsing per
    record the way the two predecessors did.
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


#: Declared type per field, taken from the two dataclasses so a new field is
#: covered without a paired edit here.
#:
#: `ModelFacts` uses `from __future__ import annotations`, so ITS field types
#: arrive as strings (`"bool"`) while `ProviderCapabilities`' arrive as real
#: classes. Normalising both to classes here is what makes the coercion
#: below apply to both records — reading `f.type` naively silently covered
#: only one of them, which is how a `"false"` model field stayed truthy.
_TYPE_NAMES: Dict[Any, Any] = {"bool": bool, "int": int, "str": str}


def _declared_type(raw: Any) -> Any:
    if isinstance(raw, str):
        return _TYPE_NAMES.get(raw)
    return raw if raw in (bool, int, str) else None


_FIELD_TYPES: Dict[str, Any] = {
    **{f.name: _declared_type(f.type) for f in dataclass_fields(ModelFacts)},
    **{
        f.name: _declared_type(f.type)
        for f in dataclass_fields(ProviderCapabilities)
    },
}

_TRUE = frozenset({"true", "1", "yes", "on"})
_FALSE = frozenset({"false", "0", "no", "off"})


def coerce_field(field: str, value: Any) -> Any:
    """Coerce a config value to the field's declared type.

    Hand-edited JSON is the documented config path, so `"false"` and
    `"4096"` arrive as strings — and both are silently wrong without this:
    `"false"` is TRUTHY, and a string `max_tokens` reaches `max()` in
    `chat.py` and raises `TypeError` mid-chat rather than at load.

    Returns the value unchanged when it cannot be coerced; `/doctor` reports
    those via :func:`wrong_typed_fields_in_config` rather than this function
    guessing. Same stance as everywhere else in this module: a config typo
    degrades one field, it never takes a request down.
    """
    declared = _FIELD_TYPES.get(field)
    if declared is None or isinstance(value, bool) and declared is bool:
        return value
    if declared is bool:
        if isinstance(value, str):
            low = value.strip().lower()
            if low in _TRUE:
                return True
            if low in _FALSE:
                return False
            return value
        if isinstance(value, int):
            return bool(value)
        return value
    if declared is int and not isinstance(value, bool):
        if isinstance(value, str):
            try:
                return int(value.strip())
            except ValueError:
                return value
        if isinstance(value, float) and value.is_integer():
            return int(value)
    return value


def is_wrong_typed(field: str, value: Any) -> bool:
    """True when `value` still does not match `field`'s declared type.

    Also catches a legacy `tool_mode` value with no successor: `"none"` is
    a `str` and so passes the type check, but it is not a `ToolMode` and
    the resolver would carry it straight into a comparison that treats it
    as capable. See `UNTRANSLATABLE_MODES`.
    """
    from ..engine.model_facts import ToolMode, UNTRANSLATABLE_MODES

    if field == "tool_mode":
        if value in UNTRANSLATABLE_MODES:
            return True
        return value not in getattr(ToolMode, "__args__", ())

    declared = _FIELD_TYPES.get(field)
    coerced = coerce_field(field, value)
    if declared is bool:
        return not isinstance(coerced, bool)
    if declared is int:
        return isinstance(coerced, bool) or not isinstance(coerced, int)
    if declared is str:
        return not isinstance(coerced, str)
    return False


def _stated_facts(container: Any, allowed: tuple) -> Dict[str, Any]:
    """The recognised, type-coerced entries of a container's `facts` block.

    `allowed` is the field set of the record this position denotes, so a
    misplaced field is dropped here rather than arbitrated. `/doctor`
    reports it via :func:`misplaced_fields_in_config`.
    """
    if not isinstance(container, dict):
        return {}
    block = container.get(FACTS_BLOCK)
    if not isinstance(block, dict):
        return {}
    return {
        k: coerce_field(k, v)
        for k, v in block.items()
        if k in allowed and not k.startswith("__comment")
    }


def provider_fact_overrides(
    provider: str, block: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Operator statements about the ENDPOINT (`ProviderCapabilities`)."""
    return _stated_facts(
        raw_provider_block(provider) if block is None else block,
        PROVIDER_FACT_FIELDS,
    )


def model_fact_overrides(
    provider: str, model: Optional[str], block: Optional[Dict[str, Any]] = None
) -> Dict[str, Any]:
    """Operator statements about ONE MODEL (`ModelFacts`)."""
    if not model:
        return {}
    pblock = raw_provider_block(provider) if block is None else block
    models = pblock.get("models")
    if not isinstance(models, dict):
        return {}
    return _stated_facts(models.get(model), FACT_FIELDS)


def apply_provider_overrides(
    caps: ProviderCapabilities, provider: str, block: Optional[Dict[str, Any]] = None
) -> ProviderCapabilities:
    """`caps` with the operator's endpoint statements applied."""
    stated = provider_fact_overrides(provider, block)
    if not stated:
        return caps
    merged = {f: getattr(caps, f) for f in PROVIDER_FACT_FIELDS}
    merged.update(stated)
    return ProviderCapabilities(**merged)


def resolve_model_facts(
    shipped: ModelFacts,
    provider: str,
    model: Optional[str],
    block: Optional[Dict[str, Any]] = None,
) -> ModelFacts:
    """`shipped` with the operator's per-model statements applied.

    Two rungs, exactly as Q0e specifies: the shipped table row, then the
    operator's row. No cross-level merge, no heuristics, nothing to
    arbitrate — a provider-level block cannot reach this function's result
    because `tool_mode` is not one of its fields.
    """
    return apply_overrides(shipped, model_fact_overrides(provider, model, block))


# ──────────────────────────────────────────────────────────────────────
# `/doctor` support — these read the FILE, because a moved or misplaced key
# is invisible to every accessor by construction.
# ──────────────────────────────────────────────────────────────────────


def _walk_config() -> Dict[str, Any]:
    try:
        path = find_config_file()
        if not path:
            return {}
        cfg = _load_json_config(path) or {}
    except Exception:  # noqa: BLE001
        return {}
    providers = cfg.get("providers")
    return providers if isinstance(providers, dict) else {}


def _each_block(cfg_providers: Dict[str, Any]):
    """Yield `(dotted_path, container, allowed_fields)` for every position
    that may carry a `facts` block."""
    for pname, pblock in cfg_providers.items():
        if not isinstance(pblock, dict):
            continue
        yield "providers.{}".format(pname), pblock, PROVIDER_FACT_FIELDS
        models = pblock.get("models")
        if isinstance(models, dict):
            for mname, mblock in models.items():
                if isinstance(mblock, dict):
                    yield (
                        "providers.{}.models.{}".format(pname, mname),
                        mblock,
                        FACT_FIELDS,
                    )


def legacy_blocks_in_config() -> Dict[str, List[str]]:
    """Every legacy key still in the config file, keyed by its dotted path.

    Feeds `/doctor`. Under a clean break these keys resolve to nothing, so
    only a check that reads the FILE can tell an operator their setting has
    stopped applying.
    """
    found: Dict[str, List[str]] = {}
    for prefix, container, _allowed in _each_block(_walk_config()):
        for bname in LEGACY_BLOCKS:
            block = container.get(bname)
            if not isinstance(block, dict):
                continue
            keys = [k for k in block if k in LEGACY_KEY_TRANSLATIONS]
            if keys:
                found["{}.{}".format(prefix, bname)] = keys
    return found


def incomplete_blocks_in_config() -> Dict[str, List[str]]:
    """Every `facts` block that does not state all of its record's fields.

    Returns dotted path -> the field names it leaves unstated (ADR 0012 §2
    Q0d). A partial config block is a defect, not a shorthand: with dozens of
    models an operator cannot tell whether an absent field is an intention or
    an oversight. Code rows are exempt by construction — the dataclass
    guarantees them complete — which is the asymmetry Q0d rests on.
    """
    missing: Dict[str, List[str]] = {}
    for prefix, container, allowed in _each_block(_walk_config()):
        block = container.get(FACTS_BLOCK)
        if not isinstance(block, dict):
            continue
        stated = {k for k in block if not k.startswith("__comment")}
        unstated = [f for f in allowed if f not in stated]
        if unstated:
            missing["{}.{}".format(prefix, FACTS_BLOCK)] = unstated
    return missing


def misplaced_fields_in_config() -> Dict[str, List[str]]:
    """Fields stated against the wrong record (ADR 0012 §2 Q0e).

    A model fact in a provider block, or an endpoint fact in a model block,
    is silently ignored by the resolver — which is the correct behaviour
    (there is nothing to arbitrate) but a poor experience unless something
    says so. This is what says so.
    """
    wrong: Dict[str, List[str]] = {}
    both = set(FACT_FIELDS) | set(PROVIDER_FACT_FIELDS)
    for prefix, container, allowed in _each_block(_walk_config()):
        block = container.get(FACTS_BLOCK)
        if not isinstance(block, dict):
            continue
        bad = [
            k
            for k in block
            if not k.startswith("__comment") and k in both and k not in allowed
        ]
        if bad:
            wrong["{}.{}".format(prefix, FACTS_BLOCK)] = bad
    return wrong


def wrong_typed_fields_in_config() -> Dict[str, List[str]]:
    """Fields whose value cannot be coerced to the declared type.

    The third `/doctor` finding, beside missing (Q0d) and misplaced (Q0e).
    :func:`coerce_field` rescues the common hand-edit cases (`"false"`,
    `"4096"`); what reaches here is a value no amount of coercion makes
    sense of, and the operator has to be told rather than have it silently
    ignored or silently truthy.
    """
    wrong: Dict[str, List[str]] = {}
    for prefix, container, allowed in _each_block(_walk_config()):
        block = container.get(FACTS_BLOCK)
        if not isinstance(block, dict):
            continue
        bad = [
            k
            for k, v in block.items()
            if not k.startswith("__comment")
            and k in allowed
            and is_wrong_typed(k, v)
        ]
        if bad:
            wrong["{}.{}".format(prefix, FACTS_BLOCK)] = bad
    return wrong


def complete_record_for(
    provider: str, model: Optional[str] = None
) -> Dict[str, Any]:
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
    from dataclasses import asdict

    from ..engine.model_facts import FactsResolver

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


def migration_plan() -> List[str]:
    """Human-readable `old -> new` lines for `/doctor`.

    **The target level is not always the source level**, and getting that
    wrong makes the advice actively harmful. ADR 0012 section 2 Q0e splits
    the fields across two records, so a legacy PROVIDER-level key holding a
    MODEL fact (`capabilities.native_tool_calling`, `tool_calling.mode`)
    has no valid provider-level home: written to `providers.<p>.facts` it
    would be ignored by the resolver AND flagged by
    :func:`misplaced_fields_in_config`. The operator would follow the
    advice, stay demoted, and collect a second warning for it.

    So this pushes such keys DOWN, one target per configured model —
    the same push-down Q0e mandates for the rewrite, and the same order:
    provider-level statements land on the models before anything else
    fills blanks. A legacy key holding an ENDPOINT fact keeps its
    provider-level target, and a model-level key maps in place.
    """
    lines: List[str] = []
    cfg_providers = _walk_config()

    for path, keys in sorted(legacy_blocks_in_config().items()):
        base = path.rsplit(".", 1)[0]
        is_provider_level = ".models." not in base
        pname = base.split(".", 2)[1] if base.startswith("providers.") else ""

        for key in keys:
            new_key, _ = LEGACY_KEY_TRANSLATIONS[key]
            src = "{}.{}".format(path, key)

            if is_provider_level and new_key in FACT_FIELDS:
                # A MODEL fact stated per provider: push it down.
                pblock = cfg_providers.get(pname) or {}
                models = pblock.get("models")
                names = sorted(models) if isinstance(models, dict) else []
                if names:
                    for mname in names:
                        lines.append(
                            "{}  ->  providers.{}.models.{}.{}.{}".format(
                                src, pname, mname, FACTS_BLOCK, new_key
                            )
                        )
                else:
                    lines.append(
                        "{}  ->  providers.{}.models.<model>.{}.{}  "
                        "(per model — this is a MODEL fact)".format(
                            src, pname, FACTS_BLOCK, new_key
                        )
                    )
            else:
                lines.append(
                    "{}  ->  {}.{}.{}".format(src, base, FACTS_BLOCK, new_key)
                )
    return lines
