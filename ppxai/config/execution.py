"""Readers for the `execution.*` config axis (ADR 0010 / ADR 0011).

ADR 0010's three-axis config shape: `providers` say WHO answers, `tools`
say WHAT capabilities exist tier-independently, and `execution.*` (this
axis, new top-level) says HOW each execution surface runs.

`execution.run.*` governs the one-off tier — the `/run` command family
and the `/v1/oneshot` facade (kind=oneshot runs, ADR 0009 step ①). Key
names per ADR 0011 sign-off Q5 (superseding ADR 0009's planned
`execution.oneshot.*` before anything shipped — amendment note there).
"""

from typing import Any, Dict

from .store import get_config


class _ConfigUnavailable(Exception):
    """Raised internally when the config source itself failed to load.

    Distinguishes "config says nothing about execution" (an absent block —
    normal, resolve defaults) from "config could not be read at all" (a
    hard error — every `execution.*` reader must fail SAFE, and no reader
    may fall back to a second, still-readable source; see
    `get_execution_run_config`'s dual-read).
    """


def _read_execution_block() -> Dict[str, Any]:
    """The raw top-level `execution` block, or raise `_ConfigUnavailable`."""
    try:
        cfg = get_config() or {}
    except Exception as exc:  # config source unreadable — not just absent
        raise _ConfigUnavailable(str(exc)) from exc
    return dict(cfg.get("execution", {}) or {})


def get_execution_config() -> Dict[str, Any]:
    """The raw top-level `execution` block (absent OR unreadable → {})."""
    try:
        return _read_execution_block()
    except _ConfigUnavailable:
        return {}


def get_execution_run_config() -> Dict[str, Any]:
    """`execution.run.*` with defaults resolved — the one-off tier's knobs.

    Keys (both default OFF — the shipped `/v1/oneshot` behavior is
    byte-identical until an operator opts in):

    - `web_search` (bool): expose the `web_search` fallback chain to the
      model on kind=oneshot runs — the ADR 0009 §4 enrichment loop, driven
      through the run tier by the oneshot facade (F3). The ONLY tool the
      one-off tier can ever grant (ADR 0011 "no tools by design").
    - `grounding` (bool): the provider's own NATIVE web search on the
      oneshot path (Option A — no tool exposed, perimeter unchanged).
      Dual-read: falls back to the legacy `tools.web_search
      .oneshot_grounding` key (shipped v1.19.0) until that key is retired;
      an explicit `execution.run.grounding` wins over the legacy key.

    Fail-safe: if the config source itself is unreadable, BOTH keys resolve
    to False — including `grounding`, whose legacy dual-read would otherwise
    reach a second, still-readable source (`tools.web_search
    .oneshot_grounding`) and silently enable native search on a box whose
    config failed to load. A capability must never survive the failure of
    the config that governs it.
    """
    try:
        run = dict(_read_execution_block().get("run", {}) or {})
    except _ConfigUnavailable:
        return {"web_search": False, "grounding": False}
    out: Dict[str, Any] = {"web_search": bool(run.get("web_search", False))}
    if "grounding" in run:
        out["grounding"] = bool(run["grounding"])
    else:
        try:
            from .tools import get_tool_config

            out["grounding"] = bool(
                get_tool_config("web_search").get("oneshot_grounding", False)
            )
        except Exception:
            out["grounding"] = False
    return out


def _normalize_sandbox(sb: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize the `execution.task.sandbox` block with defaults.

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


def get_execution_task_config() -> Dict[str, Any]:
    """`execution.task.*` — the tool-capable `/v1/agent/task` tier (ADR 0010).

    BREAKING (v1.19.1): these keys moved wholesale off `tools.agent.*`, with
    NO dual-read — a tier switch is not a property of the agent tool (ADR 0010
    placement rule 2). Nested per the ADR's target sketch so the security
    surface reads top-to-bottom in one block:

        execution.task.enabled                  (was tools.agent.task_tier_enabled)
        execution.task.sandbox.*                (was tools.agent.sandbox.*)
        execution.task.consent.spawn_consent    (was tools.agent.spawn_consent)
        execution.task.consent.consent_ttl_s    (was tools.agent.consent_ttl_s)
        execution.task.budgets.result_retention_s (was tools.agent.result_retention_s)

    Fail-safe: an unreadable config source resolves the tier to DISABLED with
    the sandbox defaults and consent "deny" — a capability must never survive
    the failure of the config that governs it (same rule as `execution.run`).
    """
    try:
        task = dict(_read_execution_block().get("task", {}) or {})
    except _ConfigUnavailable:
        task = {}
    consent = dict(task.get("consent", {}) or {})
    budgets = dict(task.get("budgets", {}) or {})
    return {
        # v1.19.0 — the tool-capable `/v1/agent/task` tier ships DEFAULT-OFF.
        # The tier is sandboxed in-process only (no OS isolation; ADR 0003
        # tier-d deferred) and is safe ONLY for trusted operators (threat model
        # A). Requiring an explicit opt-in makes "trusted operator" a deliberate,
        # code-enforced toggle rather than an assumption about auth config. The
        # tool-FREE tiers (`/v1/agent/run`, `/v1/oneshot`) are unaffected.
        "enabled": bool(task.get("enabled", False)),
        # v1.19.x build plan T2 — the filesystem SEAL. Confines where a
        # tool-capable run may read/write. The scoping fields are tier-agnostic;
        # `enforcement` selects HOW they're realized — "in_process" (a Python
        # path-jail in ScopedToolManager) now, "container" (read-only rootfs,
        # workdir emptyDir, skills/specs as ConfigMap mounts) under tier-d.
        # Default OFF: the jail engages ONLY when the operator sets
        # enforcement="in_process". See docs/agent-task-command-design.html §6.
        "sandbox": _normalize_sandbox(task.get("sandbox", {})),
        "consent": {
            # v1.19.0 Inc 7 — server-context spawn_subagent consent policy:
            # "deny" (default, safe) refuses a spawn that needs consent (there
            # is no interactive consent channel over /v1/agent/task); "auto"
            # lets API-driven spawns proceed with the capability SUBSET rules
            # (child grant ⊆ parent, egress ⊆ parent, no-shell, depth=1).
            # T5 UPDATE: under "deny" a /v1/agent/task spawn now PARKS the run
            # in `waiting{consent}` (AGENT_WAITING + POST .../respond) instead
            # of refusing outright; an unanswered park still DENIES when the
            # TTL below expires (fail-closed), so "deny" stays the safe default.
            "spawn_consent": consent.get("spawn_consent", "deny") or "deny",
            # v1.19.x build plan T5 — how long a `waiting{consent}` park stays
            # answerable before it resolves to a denial (seconds). Applies to
            # the interactive consent seam (spawn_subagent today; ask-user
            # later).
            "consent_ttl_s": float(consent.get("consent_ttl_s", 300.0)),
        },
        "budgets": {
            # v1.19.x build plan T6 — how long a `completed_pending_ack` run
            # holds its uncollected result before the lazy retention reaper
            # finalizes it (seconds; reaped on the next read — no timer task).
            # 0 disables the backstop (holds persist until an explicit
            # collect). Finalizing never deletes data — it only marks the run
            # GC-eligible.
            "result_retention_s": float(budgets.get("result_retention_s", 3600.0)),
        },
    }


def get_execution_default_subagent() -> Dict[str, Any]:
    """`execution.default_subagent` — provider/model for spawned sub-agents.

    BREAKING (v1.19.1, ADR 0010): moved from `tools.agent.default_subagent`
    with no dual-read. It composes grants ACROSS tiers, so it belongs at the
    `execution.*` root (ADR 0010 placement rule 3), not on a tool block.

    Used when a spawn request doesn't name a provider/model. Resolution at
    the /v1/agent/run route: request value -> this -> 400. Deliberately NOT
    the interactive session's chat provider — a sub-agent's model is per-task
    intent, not inherited from the UI.
    """
    subagent = get_execution_config().get("default_subagent", {})
    return dict(subagent) if isinstance(subagent, dict) else {}


def get_execution_profiles() -> Dict[str, Any]:
    """`execution.profiles` — named, reusable task grants (ADR 0009 §1).

    A profile is an `AgentSpec`-shaped mapping in config (same fields, same
    normalizer as a `--spec` file): `{tools?, network?, budget?, provider?,
    model?, system?, enrichment?}`. A run selects one by name
    (`--profile <name>` / `"profile"` on the wire); precedence is
    request > spec > profile > default_subagent > built-in default, with
    list fields (tools, network) REPLACING — not unioning — so a more
    specific layer can narrow (sign-off Q1).

    Returns the raw name → mapping dict (absent → {}); validation happens
    at resolve time in the route, where a bad profile is a 400.
    """
    profiles = get_execution_config().get("profiles", {})
    return dict(profiles) if isinstance(profiles, dict) else {}


def get_execution_task_default_grant() -> Dict[str, Any]:
    """`execution.task.default_grant` — the USER's own default `/task` grant
    (ADR 0009 / Item 58).

    An `AgentSpec`-shaped mapping (`{tools?, network?, budget?}` — the same
    normalizer as a spec/profile) that seeds a bare `/task "<desc>"` so a user
    can declare "these are the tools I normally want" and their environment
    just works, instead of every bare task 422-ing for a missing grant.

    A NEW PRECEDENCE LAYER, not a new power: it slots BELOW an explicit
    request/spec/skill/profile and ABOVE the built-in empty default. The
    resolved grant — whatever its source — still passes the UNCHANGED ceiling
    guards (shell-reject, `execution.egress_ceiling` clamp, tool
    kill-switches, provider validation, child⊆parent for spawns), so the user
    default lives strictly inside the operator's envelope and can never
    escalate capability. Governed by `allow_user_default` below (fail-closed
    when an operator disables it).

    Returns the raw mapping (absent / non-dict → {}); the same
    `spec_from_mapping` validator that guards profiles rejects a malformed
    shape at resolve time as a pre-start 400.
    """
    task = get_execution_config().get("task", {})
    if not isinstance(task, dict):
        return {}
    grant = task.get("default_grant", {})
    return dict(grant) if isinstance(grant, dict) else {}


def get_execution_task_allow_user_default() -> bool:
    """`execution.task.allow_user_default` — operator switch for Item 58.

    Default TRUE: a user's `execution.task.default_grant` seeds their bare
    `/task` runs. An operator running a locked-down deployment can set this
    FALSE to disable user-set defaults entirely — a bare `/task` with no
    request grant then keeps 422-ing (fail-closed posture). The default grant
    is always clamped by the egress ceiling and kill-switches regardless; this
    key governs only whether the layer is CONSULTED at all.
    """
    task = get_execution_config().get("task", {})
    if not isinstance(task, dict):
        return True
    return bool(task.get("allow_user_default", True))


def get_execution_egress_ceiling() -> Any:
    """`execution.egress_ceiling` — the deployment-wide egress cap (Q3).

    Config-only and intersective: a run's effective allowlist is the
    intersection of whatever it resolved (request/spec/profile/tool
    baselines) with this list. **Unset → None → no cap** (back-compat).
    A run can never state or raise it.

    Malformed (non-list) values raise ValueError rather than silently
    meaning "no cap" — a security ceiling must fail loud, not open.
    """
    ceiling = get_execution_config().get("egress_ceiling")
    if ceiling is None:
        return None
    if not isinstance(ceiling, list):
        raise ValueError(
            "execution.egress_ceiling must be a list of allowlist entries "
            f"(host strings or {{host, paths}}), got {type(ceiling).__name__}"
        )
    return list(ceiling)


def get_execution_collect() -> str:
    """`execution.collect` — how run results reach the active session (U4,
    ADR 0011). One global key covering the `/run` + `/task` families:

    - `"auto"` — a finished run always auto-merges its result into the
      active session; no user step (hold_result=False at launch, the
      watching client merges on completion).
    - `"yes"` (default — the shipped T6 behavior) — the run HOLDS its
      result (`completed_pending_ack`) and the user collects explicitly
      (Collect button / `collect` verb), which finalizes AND merges.
    - `"no"` — collect impossible: runs auto-finalize, the GUI renders the
      Collect button disabled, the `collect` verb warns with the enable
      hint, and no merge path is offered. The result stays on the run
      record only.

    Unknown values normalize to `"yes"` (fail toward the shipped default).
    """
    raw = str(get_execution_config().get("collect", "yes") or "yes").lower()
    return raw if raw in ("auto", "yes", "no") else "yes"


def get_effective_oneshot_path(provider: str, model: str) -> str:
    """The ADR 0009 §4 gating truth table, resolved from config alone.

    `native` (the provider's own search) beats `search-loop` (the web_search
    tool via the run tier) — enrichment XOR native, never both; anything
    else is `closed-book` (pure LLM, no context enrichment):

        grounding on AND capabilities.web_search          → "native"
        elif web_search on AND tool-calling capable       → "search-loop"
        else                                              → "closed-book"

    Tool-calling capable = native function calling OR an explicit
    per-provider/model `tool_calling` config block (the prompt-based path);
    neither signal → conservative closed-book.

    Lives on the CONFIG axis (not the oneshot route) so the commands layer
    (`/doctor`) can report the effective path per configured model without
    importing server routes — fastapi is an optional dependency there.
    """
    from .providers import get_provider_config, get_tool_calling_config

    run_cfg = get_execution_run_config()
    try:
        caps = get_provider_config(provider).get("capabilities", {}) or {}
    except Exception:
        caps = {}
    if run_cfg.get("grounding") and caps.get("web_search", False):
        return "native"
    tool_capable = bool(caps.get("native_tool_calling", False))
    if not tool_capable:
        try:
            mode = (get_tool_calling_config(provider, model) or {}).get("mode")
            tool_capable = bool(mode) and mode != "none"
        except Exception:
            tool_capable = False
    if run_cfg.get("web_search") and tool_capable:
        return "search-loop"
    return "closed-book"
