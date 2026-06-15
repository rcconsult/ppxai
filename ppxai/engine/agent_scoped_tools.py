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

from ..common.logger import get_logger

logger = get_logger("tui")

# Tools that grant shell execution. If none of these is in a run's grant,
# the shell-wrapper prompt context (rtk etc.) is off-grant guidance and is
# stripped from the scoped prompt.
_SHELL_TOOL_NAMES = {"execute_shell_command"}


def _strip_section(prompt: str, header: str) -> str:
    """Remove a markdown section starting at `header` up to the next
    same-or-higher-level (`## `) header or end of string. Used to drop the
    base renderer's global shell-wrapper block from a scoped prompt that
    didn't grant a shell tool. No-op if the header isn't present.
    """
    start = prompt.find(header)
    if start == -1:
        return prompt
    # Find the next "## " header after this section's content.
    rest = prompt.find("\n## ", start + len(header))
    if rest == -1:
        return prompt[:start].rstrip() + "\n"
    return (prompt[:start].rstrip() + "\n\n" + prompt[rest + 1:]).strip() + "\n"


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
    """

    def __init__(
        self,
        base: Any,
        grant: List[str],
        on_deny: Optional[Callable[[str], None]] = None,
    ) -> None:
        self._base = base
        self._grant = set(grant or [])
        self._on_deny = on_deny

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
        return await self._base.execute_tool(name, **kwargs)

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
        base_prompt = type(self._base).get_tools_prompt(self, working_dir=working_dir)
        if not base_prompt:
            return ""
        # The base renderer appends a global "## Shell wrapper context"
        # section (rtk etc.) whenever a shell wrapper is on PATH — gated on
        # the wrapper, NOT on the grant. That block names execute_shell_command
        # and describes shell execution, so it leaks off-grant shell guidance
        # to a run that wasn't granted a shell tool. Strip it unless a shell-
        # execution tool is actually in the grant.
        if not (self._grant & _SHELL_TOOL_NAMES):
            base_prompt = _strip_section(base_prompt, "## Shell wrapper context")
        allowed = ", ".join(sorted(self._grant)) or "(none)"
        return f"{base_prompt}\n\n[Run capability grant — you may ONLY call: {allowed}]"

    def get_tool(self, name: str):
        return self._base.get_tool(name) if self._granted(name) else None

    # --- delegate everything else to the base manager -------------------

    def __getattr__(self, item: str) -> Any:
        # Only called for attributes not defined above. Forwards provider/
        # model state, history, loop detection, max_iterations, etc.
        return getattr(self._base, item)
