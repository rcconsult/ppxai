"""
Tool, shell, agent, visualization, and container configuration.
"""

from typing import Any, Dict, List

from .defaults import (
    DEFAULT_AGENT_AUTO_RETRY_EMPTY,
    DEFAULT_AGENT_CONTEXT_CHAR_LIMIT,
    DEFAULT_AGENT_MAX_ITERATIONS,
    DEFAULT_AGENT_MAX_SAME_TOOL_CALLS,
    DEFAULT_AGENT_MAX_TOOL_ITERATIONS,
    DEFAULT_AGENT_MIN_TASK_WORDS,
    DEFAULT_AGENT_ZOMBIE_THRESHOLD,
    DEFAULT_ALLOWED_COMMANDS,
    DEFAULT_DANGEROUS_COMMANDS,
    DEFAULT_NEVER_ALLOW,
    DEFAULT_SHELL_WRAPPERS,
)
from .store import ConfigStore


def get_tool_config(tool_name: str) -> Dict[str, Any]:
    """Get configuration for a specific tool."""
    config = ConfigStore.get_instance().config
    tools_config = config.get("tools", {})
    return tools_config.get(tool_name, {})


def get_tool_description_overrides(provider: str = None, model: str = None) -> Dict[str, str]:
    """Get tool description overrides from config."""
    config = ConfigStore.get_instance().config
    tools_config = config.get("tools", {})
    result = {}

    global_overrides = tools_config.get("overrides", {})
    result.update(global_overrides)

    if provider:
        provider_overrides = tools_config.get("provider_overrides", {}).get(provider, {})
        result.update(provider_overrides)

    if model:
        model_overrides = tools_config.get("model_overrides", {}).get(model, {})
        result.update(model_overrides)

    return result


def get_tool_pricing(tool_name: str, provider: str) -> Dict[str, Any]:
    """Get pricing configuration for a tool provider."""
    tool_config = get_tool_config(tool_name)
    pricing = tool_config.get("pricing", {})
    return pricing.get(provider, {})


def get_shell_config() -> Dict[str, Any]:
    """Get shell tool configuration with defaults from defaults.py."""
    shell_config = get_tool_config("shell")

    default_interactive = [
        'nano', 'vim', 'vi', 'emacs', 'pico', 'joe',
        'less', 'more',
        'top', 'htop', 'btop',
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
        'ssh', 'telnet', 'ftp', 'sftp',
        'mysql', 'psql', 'mongo', 'redis-cli',
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
    ]

    default_non_interactive_with_args = [
        'python', 'python3', 'ipython', 'node', 'irb', 'ruby',
        'bash', 'zsh', 'sh', 'fish', 'csh', 'tcsh',
        'ssh',
        'mysql', 'psql',
    ]

    return {
        "require_consent": shell_config.get("require_consent", True),
        "dangerous_commands": shell_config.get("dangerous_commands", DEFAULT_DANGEROUS_COMMANDS),
        "allowed_commands": shell_config.get("allowed_commands", DEFAULT_ALLOWED_COMMANDS),
        "never_allow": shell_config.get("never_allow", DEFAULT_NEVER_ALLOW),
        "sandboxed_paths": shell_config.get("sandboxed_paths", []),
        "interactive_commands": shell_config.get("interactive_commands", default_interactive),
        "non_interactive_with_args": shell_config.get("non_interactive_with_args", default_non_interactive_with_args),
        "timeout": shell_config.get("timeout", 30),  # Default 30 seconds, configurable (v1.15.2)
        # v1.18.5: shell wrapper framework. User-facing config field
        # `tools.shell.wrappers` is merged with `DEFAULT_SHELL_WRAPPERS`
        # (the latter ships rtk as the canonical first wrapper). Conflict
        # resolution by name: user entries WIN, either overriding individual
        # fields or replacing the default entry wholesale.
        "wrappers": _resolve_wrappers(shell_config),
    }


def _resolve_wrappers(shell_config: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Merge default wrapper entries with user-declared overrides.

    Resolution rules:
    - Each default entry is matched against user entries by `name`.
    - If a user entry shares a name, its fields are merged on top of the
      default (shallow merge — `failure_markers` etc. replace, don't extend).
    - User entries with names not in the defaults are appended verbatim.
    - The order of the result preserves the default order; new user
      entries follow.

    Back-compat shim (v1.18.5 → v1.20.x):
    - `tools.shell.use_rtk` (str) overrides the rtk default's `enabled` field.
    - `tools.shell.use_rtk_prompt_hint` (bool) — when False, drops rtk's
      `prompt_block_path` so no prompt block ships even though the
      engine-side wrap stays on.
    These let users testing the v1.18.5 branch prior to the framework
    landing keep their existing config working with no edits.
    """
    user_wrappers = shell_config.get("wrappers")
    use_rtk_legacy = shell_config.get("use_rtk")
    use_rtk_prompt_hint_legacy = shell_config.get("use_rtk_prompt_hint")

    # Start with deep-ish copies of the defaults so we don't mutate the constant.
    merged: List[Dict[str, Any]] = [dict(d) for d in DEFAULT_SHELL_WRAPPERS]
    by_name = {entry["name"]: entry for entry in merged}

    # Apply legacy use_rtk* shim on the rtk default if it exists.
    if "rtk" in by_name:
        if isinstance(use_rtk_legacy, str):
            by_name["rtk"]["enabled"] = use_rtk_legacy
        if use_rtk_prompt_hint_legacy is False:
            by_name["rtk"]["prompt_block_path"] = None

    # Apply explicit user wrappers on top.
    if isinstance(user_wrappers, list):
        for user_entry in user_wrappers:
            if not isinstance(user_entry, dict) or "name" not in user_entry:
                continue
            name = user_entry["name"]
            if name in by_name:
                by_name[name].update(user_entry)
            else:
                new_entry = dict(user_entry)
                merged.append(new_entry)
                by_name[name] = new_entry

    return merged


def get_agent_config() -> Dict[str, Any]:
    """Get agent tool configuration with defaults from defaults.py."""
    agent_config = get_tool_config("agent")

    return {
        "max_iterations": agent_config.get("max_iterations", DEFAULT_AGENT_MAX_ITERATIONS),
        "max_tool_iterations": agent_config.get("max_tool_iterations", DEFAULT_AGENT_MAX_TOOL_ITERATIONS),
        "max_same_tool_calls": agent_config.get("max_same_tool_calls", DEFAULT_AGENT_MAX_SAME_TOOL_CALLS),
        "context_char_limit": agent_config.get("context_char_limit", DEFAULT_AGENT_CONTEXT_CHAR_LIMIT),
        "min_task_words": agent_config.get("min_task_words", DEFAULT_AGENT_MIN_TASK_WORDS),
        "auto_retry_empty": agent_config.get("auto_retry_empty", DEFAULT_AGENT_AUTO_RETRY_EMPTY),
        # P0 (v1.18.0) — circuit breaker for the tool loop.
        # Override via `"tools": {"agent": {"zombie_threshold": N}}` in
        # ppxai-config.json; 0 disables zombie detection entirely.
        "zombie_threshold": agent_config.get("zombie_threshold", DEFAULT_AGENT_ZOMBIE_THRESHOLD),
        # v1.19.0 agent platform — default provider/model (+ later budget)
        # for spawned sub-agent runs when the spawn request doesn't specify.
        # Resolution at the /v1/agent/run route: request value -> this ->
        # 400. Deliberately NOT the interactive session's chat provider — a
        # sub-agent's model is per-task intent, not inherited from the UI.
        # Override via `"tools": {"agent": {"default_subagent":
        # {"provider": "...", "model": "..."}}}`.
        "default_subagent": agent_config.get("default_subagent", {}),
        # v1.19.0 Inc 7 — server-context spawn_subagent consent policy:
        # "deny" (default, safe) refuses a spawn that needs consent (there is
        # no interactive consent channel over /v1/agent/task); "auto" lets
        # API-driven spawns proceed with the capability SUBSET rules (child
        # grant ⊆ parent, egress ⊆ parent, no-shell, depth=1) as the boundary.
        # Override via `"tools": {"agent": {"spawn_consent": "auto"}}`.
        # T5 UPDATE: under "deny" a /v1/agent/task spawn now PARKS the run in
        # `waiting{consent}` (AGENT_WAITING + POST .../respond) instead of
        # refusing outright; an unanswered park still DENIES when the TTL
        # below expires (fail-closed), so "deny" remains the safe default.
        "spawn_consent": agent_config.get("spawn_consent", "deny"),
        # v1.19.x build plan T5 — how long a `waiting{consent}` park stays
        # answerable before it resolves to a denial (seconds). Applies to the
        # interactive consent seam (spawn_subagent today; ask-user later).
        # Override via `"tools": {"agent": {"consent_ttl_s": 900}}`.
        "consent_ttl_s": float(agent_config.get("consent_ttl_s", 300.0)),
        # v1.19.x build plan T6 — how long a `completed_pending_ack` run holds
        # its uncollected result before the lazy retention reaper finalizes it
        # (seconds; reaped on the next read — no timer task). 0 disables the
        # backstop (holds persist until an explicit /ack). Finalizing never
        # deletes data — it only marks the run GC-eligible.
        # Override via `"tools": {"agent": {"result_retention_s": 86400}}`.
        "result_retention_s": float(agent_config.get("result_retention_s", 3600.0)),
        # v1.19.0 — the tool-capable `/v1/agent/task` tier ships DEFAULT-OFF.
        # The tier is sandboxed in-process only (no OS isolation; ADR 0003
        # tier-d deferred) and is safe ONLY for trusted operators (threat model
        # A). Requiring an explicit opt-in makes "trusted operator" a deliberate,
        # code-enforced toggle rather than an assumption about auth config. The
        # tool-FREE tiers (`/v1/agent/run`, `/v1/oneshot`) are unaffected.
        # Override via `"tools": {"agent": {"task_tier_enabled": true}}`.
        "task_tier_enabled": agent_config.get("task_tier_enabled", False),
        # v1.19.x build plan T2 — the filesystem SEAL. Confines where a
        # tool-capable run may read/write. The scoping fields are tier-agnostic;
        # `enforcement` selects HOW they're realized — "in_process" (a Python
        # path-jail in ScopedToolManager) now, "container" (read-only rootfs,
        # workdir emptyDir, skills/specs as ConfigMap mounts) under tier-d.
        # Default OFF: the jail engages ONLY when the operator sets
        # enforcement="in_process" — otherwise a tool-capable run reads/writes
        # as before (non-breaking). See docs/agent-task-command-design.html §6.
        "sandbox": _normalize_sandbox(agent_config.get("sandbox", {})),
    }


def _normalize_sandbox(sb: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the `tools.agent.sandbox` block with defaults.

    `enforcement` defaults to "off" — a run is NOT confined unless the operator
    opts in. Keys ship WITH the enforcer (never before): parsing them does
    nothing until `enforcement == "in_process"` wires the jail in
    build_task_runner; the `container` sub-block is defined but inert until
    tier-d.
    """
    sb = sb or {}
    wd = sb.get("workdir", {}) or {}
    rp = sb.get("read_paths", {}) or {}
    return {
        "enforcement": sb.get("enforcement", "off"),  # "off" | "in_process" | "container"
        "workdir": {
            "root": wd.get("root", "~/.ppxai/runs"),
            "writable": bool(wd.get("writable", True)),
            "cleanup": wd.get("cleanup", "keep"),      # "keep" | "on_finalize"
        },
        "read_paths": {
            "allow": list(rp.get("allow", []) or []),
            "deny": list(rp.get("deny", []) or []),
            "follow_symlinks": bool(rp.get("follow_symlinks", False)),
        },
        "skills_dir": sb.get("skills_dir"),
        "specs_dir": sb.get("specs_dir"),
        "allow_skill_scripts": bool(sb.get("allow_skill_scripts", False)),
        "container": sb.get("container", {}) or {},    # inert until tier-d
    }


def get_visualization_config() -> Dict[str, Any]:
    """Get data visualization configuration."""
    config = ConfigStore.get_instance().config
    viz_config = config.get("visualization", {})

    return {
        "max_rows": viz_config.get("max_rows", 10000),
        "max_columns": viz_config.get("max_columns", 50),
        "page_size": viz_config.get("page_size", 50),
        "tree_depth": viz_config.get("tree_depth", 3),
        "auto_detect": viz_config.get("auto_detect", True),
        "csv_delimiter": viz_config.get("csv_delimiter", "auto"),
        "theme": viz_config.get("theme", "default"),
    }


def get_container_config() -> Dict[str, Any]:
    """Get container tools configuration."""
    tool_config = get_tool_config("container")

    return {
        "enabled": tool_config.get("enabled", True),
        "require_consent": tool_config.get("require_consent", True),
        "default_runtime": tool_config.get("default_runtime", "auto"),
        "timeout": tool_config.get("timeout", 60),
    }


def get_vision_model_config() -> Dict[str, Any]:
    """Get vision-language sidecar configuration (v1.17.4 Phase 2.7).

    Returns the `tools.vision_model` section with sensible defaults for
    every field. When `enabled` is False (the default), the VL sidecar
    is not used and text-only models fall back to the placeholder path
    in `file_preprocessing`.

    Callers typically check `result["enabled"]` first, then read the
    rest of the fields only when the sidecar is active. The endpoint
    and model are required for calls to succeed — an enabled config
    with missing endpoint is considered disabled by `EngineClient`.
    """
    tool_config = get_tool_config("vision_model")

    return {
        "enabled": tool_config.get("enabled", False),
        "endpoint": tool_config.get("endpoint", ""),
        "model": tool_config.get("model", ""),
        "api_key_env": tool_config.get("api_key_env", ""),
        "auto_caption": tool_config.get("auto_caption", True),
        "timeout": tool_config.get("timeout", 30),
        "max_tokens": tool_config.get("max_tokens", 200),
        "prompt": tool_config.get(
            "prompt",
            "Describe this image in one or two sentences. Focus on what "
            "would help a text-only language model reason about it.",
        ),
    }
