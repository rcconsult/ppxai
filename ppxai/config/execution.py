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
