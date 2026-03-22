"""
Bootstrap context operations — AGENTS.md/CLAUDE.md loading and hint resolution.

Extracted from engine/client.py (v1.17.1) to reduce EngineClient size.
All functions take an engine reference as first parameter.
"""

from typing import Any, Dict


def load_bootstrap_context(engine) -> bool:
    """Load bootstrap context from AGENTS.md/CLAUDE.md across all scopes.

    Scopes searched:
    1. ~/.ppxai/AGENTS.md (global defaults)
    2. {git_root}/AGENTS.md (project-specific)
    3. {cwd}/AGENTS.md (subdirectory overrides)

    Returns:
        True if bootstrap context was loaded, False if no file found
    """
    ctx, sources = engine.context_injector.load_bootstrap_context_merged()
    if ctx:
        engine._bootstrap_context = ctx
        engine._bootstrap_sources = sources
        return True
    else:
        engine._bootstrap_context = None
        engine._bootstrap_sources = []
        return False


def get_bootstrap_status(engine) -> Dict[str, Any]:
    """Get status of loaded bootstrap context.

    Returns:
        Dict with loaded, sources, source_paths, char_count, has_hints,
        provider_hints, model_hints, total_size
    """
    if not engine._bootstrap_context:
        return {
            "loaded": False,
            "sources": [],
            "source_paths": [],
            "char_count": 0,
            "has_hints": False,
            "provider_hints": [],
            "model_hints": [],
            "total_size": 0,
        }

    sources_info = []
    total_size = 0
    for src in engine._bootstrap_sources:
        sources_info.append({
            "path": str(src.path),
            "scope": src.scope,
            "size": src.size,
        })
        total_size += src.size

    return {
        "loaded": True,
        "sources": sources_info,
        "source_paths": [str(src.path) for src in engine._bootstrap_sources],
        "char_count": engine._bootstrap_context.char_count,
        "has_hints": engine._bootstrap_context.has_hints,
        "provider_hints": list(engine._bootstrap_context.provider_hints.keys()),
        "model_hints": list(engine._bootstrap_context.model_hints.keys()),
        "total_size": total_size,
    }


def get_bootstrap_prompt(engine) -> str:
    """Get the bootstrap prompt for the current provider/model.

    Returns:
        Assembled bootstrap prompt string, or empty string if not loaded
    """
    if not engine._bootstrap_context:
        return ""
    return engine._bootstrap_context.get_prompt_for(engine.provider_name, engine.model)


def get_active_hints(engine) -> Dict[str, Any]:
    """Get detailed breakdown of active hints for current provider/model.

    Returns:
        Dict with loaded, source, sources, provider, model,
        provider_hints, model_hints, inherited_local, matched_patterns,
        all_provider_keys, all_model_patterns
    """
    if not engine._bootstrap_context:
        return {
            "loaded": False,
            "source": "",
            "sources": [],
            "provider": engine.provider_name,
            "model": engine.model,
            "provider_hints": [],
            "model_hints": [],
            "inherited_local": False,
            "matched_patterns": [],
            "all_provider_keys": [],
            "all_model_patterns": [],
        }

    active = engine._bootstrap_context.get_active_hints_for(
        engine.provider_name, engine.model
    )

    sources_info = [
        {"path": str(src.path), "scope": src.scope, "size": src.size}
        for src in engine._bootstrap_sources
    ]

    return {
        "loaded": True,
        "source": engine._bootstrap_context.source_file,
        "sources": sources_info,
        "provider": engine.provider_name,
        "model": engine.model,
        "provider_hints": active["provider_hints"],
        "model_hints": active["model_hints"],
        "inherited_local": active["inherited_local"],
        "matched_patterns": active["matched_patterns"],
        "all_provider_keys": list(engine._bootstrap_context.provider_hints.keys()),
        "all_model_patterns": list(engine._bootstrap_context.model_hints.keys()),
    }
