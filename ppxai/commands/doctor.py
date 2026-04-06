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


def handle_doctor(context: CommandContext, args: str) -> CommandResult:
    """Handle /doctor command — scan config and report deprecated models.

    Accepts no arguments. Returns a NotificationResult with the full
    audit report, or an ErrorResult if the config file cannot be read.
    """
    audit = audit_user_config()

    if audit["error"]:
        return ErrorResult(
            status=ResultStatus.ERROR,
            message=f"/doctor: {audit['error']}",
        )

    report = _format_audit_report(audit)

    # Escalate the result status when dead models are present so clients
    # that color by status highlight the warning appropriately.
    has_dead = bool(audit["dead"])
    has_warnings = bool(audit["upcoming"]) or bool(audit["default_warnings"])

    if has_dead:
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
        },
    )


# =============================================================================
# Command Registration
# =============================================================================

CommandFactory.register(CommandSpec(
    name="doctor",
    description="Scan config for deprecated models + health check",
    handler=handle_doctor,
    category="utility",
    usage="/doctor",
))
