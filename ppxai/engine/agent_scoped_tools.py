"""Per-run tool allowlist enforcement (ADR 0003 §3a/§4, AC-1) — Inc 4.

A tool-capable agent run (`POST /v1/agent/task`) carries a capability
grant: the set of tool names it may call. `ScopedToolManager` is the
enforcement seam — a delegating wrapper over the real `ToolManager` that:

  1. Filters the OFFERED tool set (openai-format list, prompt, list_tools,
     get_available_tools) to the grant, so the model is never even shown a
     tool it can't use.
  2. Hard-denies `execute_tool` for any name outside the grant — the
     backstop, in case a model fabricates a call to an unoffered tool.

Both layers matter: (1) is correctness/efficiency (model can't waste calls
on tools it can't use), (2) is the AC-1 security invariant (the chokepoint
proves no off-grant tool can execute, regardless of what the model emits).

`ScopedToolManager` delegates every other attribute to the base manager
(provider/model state, history, loop detection, etc.) so `chat_with_tools`
treats it exactly like a normal manager — it just sees a smaller toolset.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .tools.network_policy import (
    NetworkPolicy,
    SHELL_TOOL_NAMES,
    is_network_tool,
)
from ..common.logger import get_logger

logger = get_logger("tui")

# Single source of truth lives in network_policy (the egress module); aliased
# here for the existing prompt-stripping references. If none of these is in a
# run's grant, the shell-wrapper prompt context (rtk etc.) is off-grant
# guidance and is stripped from the scoped prompt.
_SHELL_TOOL_NAMES = SHELL_TOOL_NAMES


class ToolDenied(Exception):
    """Raised when a run attempts a tool outside its capability grant."""


class ScopedToolManager:
    """Allowlist-scoped view over a base ToolManager (AC-1 seam).

    Args:
        base: the real ToolManager (owns registration, provider state, …).
        grant: tool names this run may call. Empty grant = no tools (a
               tool-capable run with an empty grant can call nothing, which
               is a valid — if useless — sandbox; the /task route rejects
               empty grants up front, so this is defensive).
        on_deny: optional callback(name) invoked when an off-grant tool is
                 attempted — the route wires this to emit a `tool_denied`
                 run event.
        network_policy: per-run egress allowlist (AC-2, Inc 5). When set,
                 every network-capable tool call is checked against it at
                 the execute chokepoint BEFORE the request fires. When None,
                 no egress enforcement applies (a tool-free or trusted run).
        on_network: optional callback(allowed, payload) invoked on every
                 network-capable tool call — the route wires this to emit
                 `network_policy_allowed` / `network_policy_denied` events.
    """

    def __init__(
        self,
        base: Any,
        grant: List[str],
        on_deny: Optional[Callable[[str], None]] = None,
        network_policy: Optional[NetworkPolicy] = None,
        on_network: Optional[Callable[[bool, dict], None]] = None,
    ) -> None:
        self._base = base
        self._grant = set(grant or [])
        self._on_deny = on_deny
        self._network_policy = network_policy
        self._on_network = on_network

    # --- the allowlist (the whole point) --------------------------------

    def _granted(self, name: str) -> bool:
        return name in self._grant

    async def execute_tool(self, name: str, **kwargs) -> str:
        """AC-1 chokepoint: deny any tool not in the grant, else delegate.

        This is the single point every tool call in a `chat_with_tools`
        loop flows through. An off-grant name never reaches the real tool.
        """
        if not self._granted(name):
            logger.warning(
                f"Tool denied (off-grant): {name!r} not in run grant {sorted(self._grant)}"
            )
            if self._on_deny is not None:
                self._on_deny(name)
            # Return a model-readable denial rather than raising, so the
            # tool loop can continue and the model can adapt. The denial is
            # the authoritative outcome — the tool did NOT run.
            return (
                f"Error: tool {name!r} is not permitted for this run. "
                f"Permitted tools: {', '.join(sorted(self._grant)) or '(none)'}."
            )
        # AC-2 backstop: a shell-execution tool runs arbitrary commands whose
        # egress the allowlist cannot inspect, so it bypasses the chokepoint
        # below. The /v1/agent/task route rejects shell grants up front; this
        # is defense-in-depth for any other construction path — whenever an
        # egress policy is active, shell never executes.
        if self._network_policy is not None and name in SHELL_TOOL_NAMES:
            logger.warning(
                f"Tool denied (shell under egress policy): {name!r} cannot be "
                f"contained by the egress allowlist (AC-2)"
            )
            if self._on_network is not None:
                self._on_network(False, {
                    "tool": name, "target_host": "", "target_path": "",
                    "reason": "shell execution cannot be egress-confined (AC-2)",
                    "allowlist_rule_id": None,
                })
            return (
                f"Error: {name!r} is not permitted in a tool-capable agent run "
                f"(shell escapes the egress allowlist; requires OS isolation)."
            )
        # AC-2 egress chokepoint: a granted but network-capable tool must
        # also pass the run's egress allowlist before its request fires.
        # Fail-closed — no policy on a tool-capable run = no outbound.
        if self._network_policy is not None and is_network_tool(name):
            denial = self._check_network(name, kwargs)
            if denial is not None:
                return denial  # request never fired; model-readable
        return await self._base.execute_tool(name, **kwargs)

    def _check_network(self, name: str, kwargs: dict) -> Optional[str]:
        """Run the egress check for a network tool. Returns a model-readable
        denial string if blocked (and the request must NOT fire), or None if
        allowed. Emits the typed NETWORK_POLICY_* event either way.

        Uses `authorize` (not a single-URL check): a tool is allowed only if
        EVERY URL it could reach is in the allowlist — so a tool whose backend
        is chosen at call time (web_search) can't slip past by taking a branch
        we didn't predict (AC-2 superset rule)."""
        d = self._network_policy.authorize(name, kwargs)
        payload = {
            "tool": name,
            "target_host": d.target_host,
            "target_path": d.target_path,
            # Full superset of approved hosts (Item 37h): a multi-backend tool
            # picks one at call time, so the audit event records every approved
            # candidate, not just target_host (the first). Empty on deny.
            "approved_targets": list(d.approved_targets),
            "reason": d.reason,
            "allowlist_rule_id": d.rule_id,
        }
        if d.allowed:
            if self._on_network is not None:
                self._on_network(True, payload)
            return None
        logger.warning(
            f"Egress denied: tool {name!r} target {d.target_host!r} — {d.reason}"
        )
        if self._on_network is not None:
            self._on_network(False, payload)
        return (
            f"Error: network access denied for {name!r}: {d.reason}. "
            f"This run's egress allowlist did not permit that target."
        )

    # --- filtered OFFERED set (model never sees off-grant tools) ---------

    def get_available_tools(self) -> List[Any]:
        return [t for t in self._base.get_available_tools() if self._granted(t.name)]

    def list_tools(self) -> List[Dict[str, Any]]:
        return [t for t in self._base.list_tools() if self._granted(t.get("name"))]

    def get_tools_openai_format(self) -> List[Dict[str, Any]]:
        out = []
        for spec in self._base.get_tools_openai_format():
            # OpenAI tool spec shape: {"type": "function", "function": {"name": ...}}
            fn = spec.get("function", {}) if isinstance(spec, dict) else {}
            if self._granted(fn.get("name")):
                out.append(spec)
        return out

    def get_tools_prompt(self, working_dir: Optional[str] = None) -> str:
        # AC-1: the prompt-based / native-fallback path uses get_tools_prompt
        # to tell the model which tools exist — so it MUST enumerate only the
        # grant, not every registered tool. The base renderer builds from
        # `self.get_available_tools()` and `self._get_tool_description(tool)`;
        # we invoke it BOUND TO THIS SCOPED MANAGER (type(base).get_tools_prompt
        # with self=self), so `self.get_available_tools()` resolves to our
        # FILTERED override (granted tools only) while `_get_tool_description`
        # delegates to the base via __getattr__. Result: a prompt that
        # enumerates only granted tools — the offered set is truly filtered,
        # not just annotated. The allowlist note stays as a belt-and-suspenders
        # reinforcement.
        # The base renderer appends a global "## Shell wrapper context" block
        # (rtk etc.) whenever a shell wrapper is on PATH — gated on the wrapper,
        # NOT on the grant. That block names execute_shell_command and describes
        # shell execution, so it would leak off-grant shell guidance to a run
        # without a shell tool. We gate it at the SOURCE via
        # include_wrapper_context (v1.19.0 Item 37g) — emitting only when the
        # grant actually contains a shell tool — rather than emitting then
        # parsing the section back out by markdown-substring slicing (which
        # silently breaks if the renderer changes the heading level/format).
        has_shell_grant = bool(self._grant & _SHELL_TOOL_NAMES)
        base_prompt = type(self._base).get_tools_prompt(
            self, working_dir=working_dir, include_wrapper_context=has_shell_grant
        )
        if not base_prompt:
            return ""
        allowed = ", ".join(sorted(self._grant)) or "(none)"
        return f"{base_prompt}\n\n[Run capability grant — you may ONLY call: {allowed}]"

    def get_tool(self, name: str):
        return self._base.get_tool(name) if self._granted(name) else None

    # --- delegate everything else to the base manager -------------------

    def __getattr__(self, item: str) -> Any:
        # Only called for attributes not defined above. Forwards provider/
        # model state, history, loop detection, max_iterations, etc.
        return getattr(self._base, item)
