"""
/doctor — read-only config advisor.

Phase 2.4 (v1.17.4). Scans the user's `ppxai-config.json` and reports
four things:

    1. Dead models  — already shut down, listed with exact JSON paths
       so the user can remove them from their config
    2. Upcoming deprecations — still running, with days-remaining
       countdown so the user can plan migration
    3. New models available — present in the bundled example config
       but not in the user's config, with a one-line "why consider"
    4. Recommended defaults — flags `default_model` if it's on the
       deprecation list

**Read-only contract**: /doctor never writes to the user's config file.
It prints actionable information and returns exit code 0. Users apply
remediations manually — the model is their config, not ours.

Optionally integrated with a one-time startup warning (suppressed via
`PPXAI_SKIP_CONFIG_CHECK=1`) so users learn about dead models before
hitting them mid-conversation. The startup check reuses the same
classification logic via `audit_user_config()`.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..config import find_config_file
from ..engine.model_deprecations import (
    RECOMMENDED_DEFAULTS,
    audit_config_models,
    classify_model,
    find_missing_recommended,
)
from .factory import CommandFactory, CommandSpec
from .protocol import CommandContext
from .results import (
    CommandResult,
    ErrorResult,
    NotificationResult,
    ResultStatus,
)

# Per-endpoint timeout (seconds) for /doctor probe. Short on purpose:
# /doctor must stay snappy even when one of N providers is unreachable.
_PROBE_TIMEOUT_S = 2.0


def _extract_provider_models(config_data: Dict[str, Any]) -> Dict[str, List[str]]:
    """Pull (provider → [model_ids]) out of a loaded config dict.

    Walks `providers.<name>.models.<model_id>` entries and drops any
    keys starting with `__comment` (those are inline documentation
    markers, not real model IDs).
    """
    result: Dict[str, List[str]] = {}
    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return result
    for provider_name, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        models = provider_cfg.get("models", {})
        if not isinstance(models, dict):
            continue
        real_models = [
            name for name in models.keys()
            if not name.startswith("__comment")
        ]
        if real_models:
            result[provider_name] = real_models
    return result


def _extract_default_models(config_data: Dict[str, Any]) -> Dict[str, str]:
    """Return {provider: default_model} for every provider that has one set."""
    defaults: Dict[str, str] = {}
    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return defaults
    for provider_name, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        default = provider_cfg.get("default_model")
        if default and isinstance(default, str):
            defaults[provider_name] = default
    return defaults


def audit_user_config(
    config_path: Optional[Path] = None,
    *,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """Load a config file from disk and run the full audit.

    Returns a structured dict with four keys:

        {
            "config_path": str | None,
            "dead": [...],                   # shutdown entries
            "upcoming": [...],               # deprecated entries
            "missing_recommended": [...],    # new models to consider
            "default_warnings": [...],       # default_model is deprecated
            "error": str | None,             # if file missing or malformed
        }

    The caller (slash command, startup check) formats these into
    human-readable output. Separating the audit from the formatting
    lets tests assert on the raw data structure without touching Rich
    rendering.
    """
    result: Dict[str, Any] = {
        "config_path": None,
        "dead": [],
        "upcoming": [],
        "missing_recommended": [],
        "default_warnings": [],
        "error": None,
    }

    if config_path is None:
        config_path = find_config_file()

    if config_path is None:
        result["error"] = (
            "No config file found. /doctor needs a ppxai-config.json to "
            "scan — create one via `cp ppxai-config.example.json "
            "~/.ppxai/ppxai-config.json` and edit it."
        )
        return result

    result["config_path"] = str(config_path)

    try:
        with open(config_path, "r", encoding="utf-8-sig") as f:
            data = json.load(f)
    except FileNotFoundError:
        result["error"] = f"Config file missing at {config_path}"
        return result
    except json.JSONDecodeError as exc:
        result["error"] = f"Config file at {config_path} is not valid JSON: {exc}"
        return result
    except OSError as exc:
        result["error"] = f"Cannot read {config_path}: {exc}"
        return result

    provider_models = _extract_provider_models(data)
    default_models = _extract_default_models(data)

    audit = audit_config_models(provider_models, today=today)
    result["dead"] = audit["dead"]
    result["upcoming"] = audit["upcoming"]

    result["missing_recommended"] = find_missing_recommended(provider_models)

    # Flag any provider whose default_model is on the deprecation list.
    for provider, default in default_models.items():
        info = classify_model(default, today=today)
        if info is not None:
            result["default_warnings"].append({
                "provider": provider,
                "default_model": default,
                "status": info["status"],
                "shutdown_date": info["shutdown_date"],
                "replacement": info["replacement"],
                "recommended_default": RECOMMENDED_DEFAULTS.get(provider, ""),
            })

    return result


def _format_audit_report(audit: Dict[str, Any]) -> str:
    """Render an audit dict as a human-readable plain-text report.

    Used by /doctor for its main output and by the startup warning for
    the "one-liner + short summary" variant. The return value is a
    single string with embedded newlines — callers (Rich / Textual)
    pass it through their usual text rendering.
    """
    lines: List[str] = []

    lines.append("ppxai config check")
    lines.append("==================")
    lines.append(f"Config: {audit['config_path'] or '(none found)'}")
    lines.append("")

    dead = audit["dead"]
    upcoming = audit["upcoming"]
    missing = audit["missing_recommended"]
    default_warnings = audit["default_warnings"]

    if not dead and not upcoming and not missing and not default_warnings:
        lines.append("✓ No issues found. Your config is up to date.")
        return "\n".join(lines)

    if dead:
        lines.append(
            f"⚠ Dead models in config ({len(dead)} — must remove or replace):"
        )
        for entry in dead:
            provider = entry["provider"]
            model = entry["model"]
            shutdown = entry["shutdown_date"]
            replacement = entry["replacement"]
            lines.append(
                f"   providers.{provider}.models.{model}"
                f" (shut down {shutdown}) → switch to {replacement}"
            )
            if entry.get("reason"):
                lines.append(f"     reason: {entry['reason']}")
        lines.append("")

    if upcoming:
        lines.append(
            f"⚠ Upcoming deprecations ({len(upcoming)} models):"
        )
        for entry in upcoming:
            provider = entry["provider"]
            model = entry["model"]
            shutdown = entry["shutdown_date"]
            days = entry.get("days_remaining", "?")
            replacement = entry["replacement"]
            lines.append(
                f"   providers.{provider}.models.{model}"
                f" → {shutdown} ({days} days) → switch to {replacement}"
            )
        lines.append("")

    if default_warnings:
        lines.append(
            f"⚠ Provider default_model set to a deprecated model "
            f"({len(default_warnings)} provider"
            f"{'s' if len(default_warnings) != 1 else ''}):"
        )
        for warn in default_warnings:
            provider = warn["provider"]
            model = warn["default_model"]
            status = warn["status"]
            recommended = warn["recommended_default"]
            rec_hint = f" — recommended: {recommended}" if recommended else ""
            lines.append(
                f"   providers.{provider}.default_model = {model!r} "
                f"({status}){rec_hint}"
            )
        lines.append("")

    if missing:
        lines.append(
            f"✓ New models available to adopt ({len(missing)}):"
        )
        for rec in missing:
            provider = rec["provider"]
            model = rec["model"]
            reason = rec["reason"]
            lines.append(f"   {provider}: {model}")
            lines.append(f"     {reason}")
        lines.append("")

    lines.append("/doctor is read-only — apply changes manually in your config file.")
    return "\n".join(lines)


def _summarize_startup(audit: Dict[str, Any]) -> Optional[str]:
    """One-line summary for the optional startup warning.

    Returns None when there's nothing worth interrupting the user about
    (no dead models). Deprecated-but-not-dead models are not flagged at
    startup — they're surfaced only when the user explicitly runs
    /doctor, to avoid alarm fatigue.
    """
    dead_count = len(audit.get("dead", []))
    if dead_count == 0:
        return None
    plural = "s" if dead_count != 1 else ""
    return (
        f"⚠ ppxai: {dead_count} dead model{plural} in your config. "
        f"Run /doctor for details."
    )


def _probe_provider_endpoint(
    provider_name: str, provider_cfg: Dict[str, Any]
) -> Dict[str, Any]:
    """Hit `<base_url>/models` and return what the endpoint advertises.

    Returns a dict shaped like:

        {
            "reachable": bool,
            "endpoint_models": {model_id: max_model_len, ...},
            "error": str | None,
        }

    Best-effort: any network/parse failure is swallowed and surfaces
    as `reachable: False` with a short error string. Never raises.
    """
    result: Dict[str, Any] = {
        "reachable": False,
        "endpoint_models": {},
        "error": None,
    }
    base_url = provider_cfg.get("base_url")
    if not base_url:
        result["error"] = "no base_url"
        return result

    api_key_env = provider_cfg.get("api_key_env")
    api_key = os.getenv(api_key_env, "") if api_key_env else ""
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    url = base_url.rstrip("/") + "/models"

    try:
        # Lazy import — keeps /doctor importable when httpx is missing
        # (we only need it for the probe path, never the offline audit).
        import httpx
    except ImportError:
        result["error"] = "httpx not installed"
        return result

    try:
        with httpx.Client(timeout=_PROBE_TIMEOUT_S) as client:
            response = client.get(url, headers=headers)
            response.raise_for_status()
            payload = response.json()
    except Exception as exc:
        result["error"] = f"{type(exc).__name__}: {str(exc)[:80]}"
        return result

    endpoint_models: Dict[str, int] = {}
    for entry in payload.get("data", []) or []:
        if not isinstance(entry, dict):
            continue
        model_id = entry.get("id")
        max_len = entry.get("max_model_len")
        if isinstance(model_id, str) and isinstance(max_len, int) and max_len > 0:
            endpoint_models[model_id] = max_len

    result["reachable"] = True
    result["endpoint_models"] = endpoint_models
    return result


def probe_all_providers(config_data: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Run `_probe_provider_endpoint` for every configured provider in parallel.

    Returns `{provider_name: probe_dict}`. Providers without a `base_url`
    or that error out still appear in the result with `reachable: False`
    so the formatter can show them as "could not reach".
    """
    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return {}

    targets = [
        (name, cfg)
        for name, cfg in providers.items()
        if isinstance(cfg, dict) and cfg.get("base_url")
    ]
    if not targets:
        return {}

    results: Dict[str, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(8, len(targets))) as pool:
        futures = {
            pool.submit(_probe_provider_endpoint, name, cfg): name
            for name, cfg in targets
        }
        for future in futures:
            name = futures[future]
            try:
                results[name] = future.result(timeout=_PROBE_TIMEOUT_S + 1.0)
            except Exception as exc:
                results[name] = {
                    "reachable": False,
                    "endpoint_models": {},
                    "error": f"timeout/{type(exc).__name__}",
                }
    return results


def detect_context_limit_drift(
    config_data: Dict[str, Any], probe_results: Dict[str, Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """Compare each model's `context_limit` to the endpoint's `max_model_len`.

    Returns a list of drift entries; over-claim is the dangerous case
    (ppxai admits prompts the backend rejects), under-claim is just a
    missed-headroom note. Models whose endpoint omits `max_model_len`
    or whose config omits `context_limit` are skipped silently.
    """
    drift: List[Dict[str, Any]] = []
    providers = config_data.get("providers", {})
    if not isinstance(providers, dict):
        return drift

    for provider_name, provider_cfg in providers.items():
        if not isinstance(provider_cfg, dict):
            continue
        probe = probe_results.get(provider_name)
        if not probe or not probe.get("reachable"):
            continue
        models = provider_cfg.get("models", {})
        if not isinstance(models, dict):
            continue
        for model_id, model_cfg in models.items():
            if model_id.startswith("__comment") or not isinstance(model_cfg, dict):
                continue
            config_limit = model_cfg.get("context_limit")
            actual_limit = probe["endpoint_models"].get(model_id)
            if not isinstance(config_limit, int) or not isinstance(actual_limit, int):
                continue
            if config_limit == actual_limit:
                continue
            drift.append({
                "provider": provider_name,
                "model": model_id,
                "config_limit": config_limit,
                "actual_limit": actual_limit,
                "severity": "over-claim" if config_limit > actual_limit else "under-claim",
            })
    return drift


def _format_probe_section(
    probe_results: Dict[str, Dict[str, Any]],
    drift: List[Dict[str, Any]],
) -> List[str]:
    """Render the probe results + drift table as plain-text lines."""
    lines: List[str] = []
    lines.append("Endpoint probe (live `/v1/models`):")
    if not probe_results:
        lines.append("   (no providers with base_url configured)")
        return lines

    unreachable = [
        (name, p) for name, p in probe_results.items() if not p.get("reachable")
    ]
    reachable = [
        (name, p) for name, p in probe_results.items() if p.get("reachable")
    ]

    if reachable:
        reachable_names = ", ".join(name for name, _ in reachable)
        lines.append(f"   ✓ Reachable: {len(reachable)} ({reachable_names})")
    if unreachable:
        unreachable_parts = [
            f"{name} [{(probe.get('error') or '?')}]"
            for name, probe in unreachable
        ]
        lines.append(
            f"   ⚠ Unreachable: {len(unreachable)} ({', '.join(unreachable_parts)})"
        )

    over = [d for d in drift if d["severity"] == "over-claim"]
    under = [d for d in drift if d["severity"] == "under-claim"]

    if over:
        lines.append("")
        lines.append(
            f"⚠ Context-limit OVER-CLAIM ({len(over)} — config exceeds backend `--max-model-len`):"
        )
        for d in over:
            lines.append(
                f"   providers.{d['provider']}.models.{d['model']}.context_limit = "
                f"{d['config_limit']:,} but endpoint reports {d['actual_limit']:,}"
            )
            lines.append(
                f"     → fix: lower context_limit to {d['actual_limit']:,} (or align backend)"
            )
    if under:
        lines.append("")
        lines.append(
            f"ℹ Context-limit under-claim ({len(under)} — leaves headroom unused):"
        )
        for d in under:
            lines.append(
                f"   providers.{d['provider']}.models.{d['model']}.context_limit = "
                f"{d['config_limit']:,} but endpoint allows {d['actual_limit']:,}"
            )
    if not over and not under and reachable:
        lines.append("   ✓ context_limit values match endpoint advertisements")
    return lines


def _format_grounding_section() -> List[str]:
    """Oneshot grounding path per configured provider (F5, ADR 0009 §4).

    Offline — resolved from config alone via the SAME function the
    /v1/oneshot route uses (`config.execution.get_effective_oneshot_path`),
    so what /doctor prints is what a request will actually do:
    native (provider-side search) / search-loop (web_search tool via the
    run tier) / closed-book (pure LLM, no context enrichment).
    """
    from ..config import get_available_providers, get_default_model
    from ..config.execution import (
        get_effective_oneshot_path,
        get_execution_run_config,
    )

    lines: List[str] = []
    lines.append("Oneshot grounding (execution.run):")
    try:
        run_cfg = get_execution_run_config()
    except Exception:
        run_cfg = {"web_search": False, "grounding": False}
    lines.append(
        f"   web_search={'on' if run_cfg.get('web_search') else 'off'}"
        f"  grounding={'on' if run_cfg.get('grounding') else 'off'}"
        f"  (both off = pure LLM, air-gap-safe)"
    )
    try:
        providers = get_available_providers()
    except Exception:
        providers = []
    if not providers:
        lines.append("   (no providers configured)")
        return lines
    labels = {
        "native": "native — provider-side search, no new egress",
        "search-loop": "search-loop — web_search tool via the run tier "
                       "(auditable kind=oneshot run)",
        "closed-book": "closed-book — pure LLM, no enrichment",
    }
    for p in providers:
        try:
            model = get_default_model(p)
        except Exception:
            model = None
        try:
            path = get_effective_oneshot_path(p, model or "")
        except Exception:
            path = "closed-book"
        lines.append(f"   {p} ({model or 'no default model'}): {labels[path]}")
    return lines


def _format_web_search_backend_section() -> List[str]:
    """web_search backend tuple report + the three Q5 config checks
    (ADR 0009 step ④). Offline — reads the SAME shared resolver the search
    chain and the egress enumeration use, so what /doctor prints is what a
    call will actually do.

    Checks:
    (a) a concrete `preferred` WITHOUT `strict` — since v1.19.1 this is an
        ordering, not a pin: the fallback chain stays live and egress is the
        full superset (WIDER than pre-upgrade). Operators who wanted the old
        hard pin must add `strict: true`.
    (b) a per-provider `strict` without a per-provider `preferred` in the
        same block — a dead key by construction (the Q5 tuple resolves scope
        first; `strict` is only read from the scope that owns `preferred`).
    (c) `strict: true` while enrichment is in play (an execution profile
        with `enrichment: true`, or `execution.run.web_search` on) — legal,
        but the run loses the fallback chain: one backend outage returns it
        to closed-book.
    """
    from ..config import get_available_providers, get_provider_config, get_tool_config
    from ..engine.tools.search_backends import resolve_web_search_backend

    lines: List[str] = []
    lines.append("web_search backend (tools.web_search preferred/strict — Q5 tuple):")

    res = resolve_web_search_backend(None)
    lines.append(
        f"   global: preferred={res.preferred} strict={str(res.strict).lower()} "
        f"→ chain: {' → '.join(res.candidates) or '(none usable)'}"
    )
    warnings: List[str] = list(res.warnings)

    try:
        g = get_tool_config("web_search") or {}
    except Exception:
        g = {}
    if g.get("preferred") and g.get("preferred") != "auto" and not g.get("strict"):
        warnings.append(
            f"global preferred={g['preferred']!r} without strict — since "
            "v1.19.1 this ORDERS the chain (fallback live, egress = full "
            "superset, WIDER than the old hard pin). Add "
            "tools.web_search.strict:true to keep the pin."
        )

    try:
        providers = get_available_providers()
    except Exception:
        providers = []
    for p in providers:
        try:
            block = (get_provider_config(p) or {}).get("web_search", {}) or {}
        except Exception:
            block = {}
        if not block:
            continue
        pres = resolve_web_search_backend(p)
        if pres.scope.startswith("provider:"):
            lines.append(
                f"   {p}: preferred={pres.preferred} "
                f"strict={str(pres.strict).lower()} → chain: "
                f"{' → '.join(pres.candidates) or '(none usable)'}"
            )
        warnings.extend(w for w in pres.warnings if w not in warnings)
        if (block.get("preferred") and block.get("preferred") != "auto"
                and not block.get("strict")):
            warnings.append(
                f"providers.{p}.web_search.preferred={block['preferred']!r} "
                "without strict — ordering, not a pin (see the global note)."
            )

    # (c) strict pin while enrichment is in play — legal, chain-costing.
    strict_anywhere = res.strict or any(
        resolve_web_search_backend(p).strict for p in providers
    )
    if strict_anywhere:
        enrichment_live: List[str] = []
        try:
            from ..config.execution import (
                get_execution_profiles,
                get_execution_run_config,
            )
            if get_execution_run_config().get("web_search"):
                enrichment_live.append("execution.run.web_search")
            enrichment_live.extend(
                f"execution.profiles.{name}"
                for name, prof in (get_execution_profiles() or {}).items()
                if isinstance(prof, dict) and prof.get("enrichment") is True
            )
        except Exception:
            pass
        if enrichment_live:
            warnings.append(
                "strict:true + enrichment "
                f"({', '.join(enrichment_live)}) — legal, but the enriched "
                "run is pinned to ONE backend: a single outage returns it to "
                "closed-book (no fallback chain)."
            )

    for w in warnings:
        lines.append(f"   ⚠ {w}")
    if not warnings:
        lines.append("   ✓ no preferred/strict config hazards")
    return lines


# ADR 0010 (v1.19.1) config-shape migration: legacy location -> new location.
# A CLEAN BREAK — there is NO dual-read, so a key left at its old location is
# silently ignored and its setting reverts to the default. That silence is
# exactly what this check exists to break: /doctor is the operator's discovery
# path for the rename.
ADR_0010_KEY_MOVES: List[tuple] = [
    (("tools", "agent", "task_tier_enabled"), "execution.task.enabled"),
    (("tools", "agent", "sandbox"), "execution.task.sandbox"),
    (("tools", "agent", "spawn_consent"), "execution.task.consent.spawn_consent"),
    (("tools", "agent", "consent_ttl_s"), "execution.task.consent.consent_ttl_s"),
    (
        ("tools", "agent", "result_retention_s"),
        "execution.task.budgets.result_retention_s",
    ),
    (("tools", "agent", "default_subagent"), "execution.default_subagent"),
]


def _lookup_path(config_data: Dict[str, Any], path: tuple) -> Any:
    """Walk a dotted key path, returning None when any segment is missing."""
    node: Any = config_data
    for segment in path:
        if not isinstance(node, dict) or segment not in node:
            return None
        node = node[segment]
    return node


def _format_config_migration_section(config_data: Dict[str, Any]) -> List[str]:
    """Report `ppxai-config.json` keys still at their pre-ADR-0010 location.

    Reads the config FILE rather than the accessors on purpose: the accessors
    no longer look at the legacy locations at all, so a stale key is invisible
    to them by construction. Only a raw file scan can tell an operator that
    the setting they wrote is being ignored.
    """
    lines: List[str] = ["Config shape (ADR 0010, v1.19.1):"]
    stale = [
        (".".join(path), new)
        for path, new in ADR_0010_KEY_MOVES
        if _lookup_path(config_data, path) is not None
    ]
    if not stale:
        lines.append("   ✓ no keys at pre-v1.19.1 locations")
        return lines

    lines.append(
        f"   ⚠ {len(stale)} key(s) at their OLD location — BREAKING change in "
        "v1.19.1, no dual-read. These are being IGNORED and have reverted to "
        "their defaults. Move them:"
    )
    for old, new in stale:
        lines.append(f"      {old}  ->  {new}")
    return lines


def handle_doctor(context: CommandContext, args: str) -> CommandResult:
    """Handle /doctor command — scan config and report deprecated models.

    Without args, runs the offline config audit only.
    With `probe`, additionally hits each provider's `<base_url>/models`
    endpoint and reports drift between configured `context_limit` and
    the backend's advertised `max_model_len`. The probe is opt-in so
    /doctor stays fast and offline-safe by default.
    """
    do_probe = "probe" in (args or "").split()
    audit = audit_user_config()

    if audit["error"]:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"/doctor: {audit['error']}",
        )

    report = _format_audit_report(audit)
    # F5 (ADR 0009 §4): per-provider effective grounding path — offline,
    # always shown, same decision function the /v1/oneshot route uses.
    report = report + "\n\n" + "\n".join(_format_grounding_section())
    # Step ④ (ADR 0009 Q5): web_search backend tuple + the three config
    # checks (ordering-not-pin upgrade note, dead per-provider strict,
    # strict-while-enriched) — offline, same resolver the chain uses.
    report = report + "\n\n" + "\n".join(_format_web_search_backend_section())
    # ADR 0010 (v1.19.1): flag keys still at their pre-migration location.
    # Offline and always shown — a stale key is silently ignored under the
    # clean break, so this is the only surface that reveals it.
    if audit.get("config_path"):
        try:
            with open(audit["config_path"], "r", encoding="utf-8-sig") as f:
                raw_config = json.load(f)
            report = report + "\n\n" + "\n".join(
                _format_config_migration_section(raw_config)
            )
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            # Never fail /doctor over the migration check.
            pass
    probe_results: Dict[str, Dict[str, Any]] = {}
    drift: List[Dict[str, Any]] = []

    if do_probe and audit.get("config_path"):
        try:
            with open(audit["config_path"], "r", encoding="utf-8-sig") as f:
                config_data = json.load(f)
            probe_results = probe_all_providers(config_data)
            drift = detect_context_limit_drift(config_data, probe_results)
            probe_lines = _format_probe_section(probe_results, drift)
            report = report + "\n\n" + "\n".join(probe_lines)
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            # Probe is opt-in best-effort; never fail /doctor over it.
            report = report + "\n\n(probe skipped — could not re-read config)"

    # Escalate the result status when dead models are present so clients
    # that color by status highlight the warning appropriately.
    has_dead = bool(audit["dead"])
    has_warnings = bool(audit["upcoming"]) or bool(audit["default_warnings"])
    has_drift_overclaim = any(d["severity"] == "over-claim" for d in drift)

    if has_dead or has_drift_overclaim:
        status = ResultStatus.WARNING
    elif has_warnings:
        status = ResultStatus.WARNING
    else:
        status = ResultStatus.SUCCESS

    return NotificationResult(
        status=status,
        message=report,
        metadata={
            "dead_count": len(audit["dead"]),
            "upcoming_count": len(audit["upcoming"]),
            "missing_recommended_count": len(audit["missing_recommended"]),
            "default_warnings_count": len(audit["default_warnings"]),
            "probed": do_probe,
            "drift_overclaim_count": sum(1 for d in drift if d["severity"] == "over-claim"),
            "drift_underclaim_count": sum(1 for d in drift if d["severity"] == "under-claim"),
        },
    )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="doctor",
    description="Scan config for deprecated models; `/doctor probe` also checks live endpoints",
    handler=handle_doctor,
    category="utility",
    usage="/doctor [probe]",
))
