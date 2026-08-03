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


def get_execution_config() -> Dict[str, Any]:
    """The raw top-level `execution` block (absent → {})."""
    try:
        return dict((get_config() or {}).get("execution", {}) or {})
    except Exception:
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
    """
    run = dict(get_execution_config().get("run", {}) or {})
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
