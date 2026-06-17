"""spawn_subagent — a run spawns one child run (ADR 0003 §9, Inc 7).

A tool-capable agent run can delegate a sub-task to a child run. The child
is a full agent run in its own right (own run_id, own EngineClient, own
events/artifacts), linked to the parent via `parent_run_id`. The parent's
tool call blocks until the child finishes, then returns the child's result.

Security — the whole point of this increment (keeps AC-1/AC-2 transitive):

  * **Child grant ⊆ parent grant.** The child may be given only tools the
    parent itself holds. A child can never gain a capability the parent
    lacks (no privilege escalation). Off-parent tool → spawn refused.
  * **Child egress ⊆ parent allowlist.** Every child `allow_outbound` host
    must be permitted by the parent's own allowlist, so a child can't reach
    a host the parent couldn't. Off-parent host → spawn refused.
  * **Depth = 1.** The child is built with `allow_spawn=False`, so it never
    receives this tool — a grandchild is structurally impossible, not
    blocked by a runtime flag the model could probe.
  * **N = 1 concurrent.** The parent awaits the child to completion before
    its tool call returns, so one parent drives at most one child at a time.
  * **Consent-gated.** Spawning requires interactive approval (same gate as
    shell), so an autonomous run can't fan out without a human in the loop.

The child shares the parent's egress-host SUBSET rules via the same
`NetworkPolicy` superset check (Inc 5) — this module only validates that the
requested child allowlist is itself within the parent's, then hands the
subset to the shared run runner.
"""

from __future__ import annotations

import asyncio
import time
from typing import Awaitable, Callable, List, Optional

from .base import BaseTool
from .network_policy import NetworkPolicy, grant_has_shell
from ...common.logger import get_logger

logger = get_logger("tui")

# Outer guard for how long a parent waits on a child before cancelling it.
# Only used when the child set no time_s budget of its own (the child's
# cooperative time budget, when present, fires first). Not a magic deadline
# the child silently survives — on hit, the parent CANCELS the child.
_DEFAULT_CHILD_WAIT_S = 300.0


class SpawnSubagentTool(BaseTool):
    """Spawn one child agent run, scoped to a subset of this run's caps."""

    name = "spawn_subagent"
    description = (
        "Delegate a sub-task to a child agent run. The child runs with a "
        "SUBSET of your own tools and network allowlist (you cannot grant it "
        "anything you don't have). Blocks until the child finishes, then "
        "returns its result. Use to parallelize or isolate a focused sub-task."
    )
    parameters = {
        "type": "object",
        "properties": {
            "task": {
                "type": "string",
                "description": "The sub-task / prompt for the child agent.",
            },
            "tools": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Tools to grant the child — MUST be a subset of your own "
                    "grant. Omit for an empty (tool-free) child."
                ),
            },
            "allow_outbound": {
                "type": "array",
                "items": {
                    "oneOf": [
                        {"type": "string"},
                        {
                            "type": "object",
                            "properties": {
                                "host": {"type": "string"},
                                "paths": {"type": "array", "items": {"type": "string"}},
                            },
                            "required": ["host"],
                        },
                    ]
                },
                "description": (
                    "Egress rules for the child — each a host string (exact or "
                    "`*.suffix`) or {host, paths:[prefix,...]}. Each MUST be "
                    "permitted by your own allowlist (host AND path scope). Omit "
                    "for no child network access."
                ),
            },
        },
        "required": ["task"],
    }

    def __init__(
        self,
        *,
        registry,
        parent_run_id: str,
        parent_tools: List[str],
        parent_allow_outbound: list,
        parent_provider: str,
        parent_model: str,
        parent_owner: Optional[str] = None,
        request_consent: Optional[Callable[[str], Awaitable[bool]]] = None,
        consent_policy: str = "deny",
    ) -> None:
        self._registry = registry
        self._parent_run_id = parent_run_id
        # Inc 8b: the child run inherits the parent's owner so per-run authz
        # scopes it to the SAME principal. Without this the child is minted
        # owner=None (world-readable to any authenticated caller) — a
        # privilege leak, since the child's transcript/result derive from the
        # parent's authorized work.
        self._parent_owner = parent_owner
        self._parent_tools = set(parent_tools or [])
        self._parent_allow_outbound = list(parent_allow_outbound or [])
        self._parent_policy = NetworkPolicy(self._parent_allow_outbound)
        self._provider = parent_provider
        self._model = parent_model
        self._request_consent = request_consent
        # Server-context consent policy (tools.agent.spawn_consent):
        #   "deny" (default, safe) — no interactive channel over HTTP, so a
        #     spawn that would need consent is refused (with a visible event).
        #   "auto" — proceed without an interactive prompt; the capability
        #     SUBSET rules (child grant ⊆ parent, child egress ⊆ parent,
        #     no-shell, depth=1) remain the enforced boundary. Use when the
        #     allowlist/grant is trusted to be the gate, not a human click.
        # The proper interactive flow (AGENT_WAITING + /respond, ADR 0003 §8)
        # supersedes this when it lands.
        self._consent_policy = consent_policy

    # --- subset enforcement (AC-1 / AC-2 transitive) --------------------

    def _check_grant_subset(self, child_tools: List[str]) -> Optional[str]:
        """Return an error string if child_tools isn't ⊆ parent grant."""
        # A child must never carry shell either (same AC-2 rule as /task).
        if grant_has_shell(child_tools):
            return "child may not be granted a shell tool (escapes egress; AC-2)"
        extra = set(child_tools) - self._parent_tools
        if extra:
            return (
                f"child tools {sorted(extra)} are not in the parent's grant "
                f"{sorted(self._parent_tools)} — no privilege escalation"
            )
        return None

    def _check_egress_subset(self, child_allow: list) -> Optional[str]:
        """Return an error string if any child egress rule isn't permitted by
        the parent allowlist — checking BOTH host and path scope, so a child
        can't widen egress on either axis.

        A child rule is `host` (string) or `{host, paths}`. We probe each
        (host, path) the child could reach against the PARENT's policy and
        require ALLOW. Critically we probe the child's *paths* (not just root):
        a parent scoped to /repos/ must accept a child asking for /repos/ but
        reject a child asking for / or /other/. With no child paths, the child
        wants any path on the host, so we probe root `/` — which the parent
        permits only if its own rule for that host is unrestricted."""
        from .network_policy import Allow

        for entry in child_allow or []:
            if isinstance(entry, str):
                host, paths = entry, []
            elif isinstance(entry, dict):
                host = entry.get("host", "")
                paths = [p for p in (entry.get("paths") or []) if isinstance(p, str)]
            else:
                return f"malformed child egress rule: {entry!r}"
            # Concrete host to probe: a "*.suffix" glob -> a representative
            # subdomain so the parent's own glob (if any) can match it.
            if not host:
                return f"malformed child egress rule (no host): {entry!r}"
            probe_host = ("sub" + host[1:]) if host.startswith("*.") else host
            # The set of paths the child could hit: each declared prefix, or
            # root if it declared none (= any path).
            probe_paths = paths or ["/"]
            for p in probe_paths:
                probe = f"https://{probe_host}{p if p.startswith('/') else '/' + p}"
                if not isinstance(self._parent_policy.check(probe), Allow):
                    scope = f"{host}{(' path ' + p) if paths else ''}"
                    return (
                        f"child egress {scope!r} is not permitted by the parent "
                        f"allowlist — child egress must be a subset (host + path)"
                    )
        return None

    # --- execution ------------------------------------------------------

    def _deny(self, reason: str, kind: str) -> str:
        """Emit a visible spawn_denied event on the parent stream AND return a
        model-readable error. No refusal is silent — an operator watching the
        run sees WHY a spawn didn't happen (the prior gap: a refused spawn only
        sent a string back to the model, leaving no trace on the event log)."""
        logger.warning(f"spawn_subagent denied ({kind}): {reason}")
        self._registry.emit_event(
            self._parent_run_id, "spawn_denied", level="warning",
            category="consent" if kind == "consent" else "lifecycle",
            data={"kind": kind, "reason": reason},
        )
        return f"Error: cannot spawn sub-agent — {reason}."

    async def execute(
        self,
        task: str,
        tools: Optional[List[str]] = None,
        allow_outbound: Optional[list] = None,
        **kwargs,
    ) -> str:
        from ...server.routes.agent_v1 import build_task_runner

        child_tools = list(tools or [])
        child_allow = list(allow_outbound or [])

        # 1. Subset enforcement — refuse BEFORE minting anything.
        err = self._check_grant_subset(child_tools)
        if err:
            return self._deny(err, "grant")
        err = self._check_egress_subset(child_allow)
        if err:
            return self._deny(err, "egress")

        # 2. Consent gate. Policy:
        #    - "auto": skip the interactive prompt; the subset rules above are
        #      the boundary. (Server context has no human to ask.)
        #    - "deny" (default): if an interactive consent channel exists, ask
        #      it; otherwise refuse with a visible event — never silently.
        if self._consent_policy != "auto":
            summary = f"spawn_subagent: {task[:80]!r} tools={child_tools}"
            if self._request_consent is None:
                return self._deny(
                    "spawn consent required but no interactive consent channel "
                    "in this context; set tools.agent.spawn_consent='auto' to "
                    "allow API-driven spawns (subset rules still apply)",
                    "consent",
                )
            approved = await self._request_consent(summary)
            if not approved:
                return self._deny("user denied permission to spawn", "consent")

        # 3. Mint the child run, linked to the parent via parent_run_id. The
        #    child is a FIRST-CLASS run with its own run_id (addressable by
        #    get_run / the /v1/agent/runs API) and its own agent-0 slot — it is
        #    NOT nested under the parent's directory. (The ADR 0005 agent-<n>
        #    nesting under one run_id is a later refinement; for the N=1 MVP a
        #    child as its own run keyed by parent_run_id is correct + simpler,
        #    and avoids an agent_n/get_run slot mismatch that would make the
        #    child unfindable by the default-agent_n lookup.)
        child = self._registry.start_run(
            task=task,
            tools=child_tools,
            provider=self._provider,
            model=self._model,
            network=child_allow,
            parent_run_id=self._parent_run_id,
            owner=self._parent_owner,  # Inc 8b: child inherits parent's owner
        )
        self._registry.emit_event(
            self._parent_run_id, "subagent_spawned", level="info",
            category="lifecycle",
            data={"child_run_id": child.run_id, "task": task[:120],
                  "tools": child_tools},
        )

        # 4. Run the child through the SAME sandbox machinery, with
        #    allow_spawn=False so it can never itself spawn (depth=1).
        runner = build_task_runner(
            self._registry,
            provider_name=self._provider,
            model=self._model,
            task=task,
            tools=child_tools,
            allow_outbound=child_allow,
            allow_spawn=False,
        )

        # 5. Run to completion and collect the result. We drive the child
        #    inline (awaited) rather than fire-and-forget so the parent's tool
        #    call returns the child's answer — N=1, parent blocks on child.
        try:
            self._registry.run_in_background(child, runner)
        except Exception as exc:  # noqa: BLE001
            return f"Error: failed to start sub-agent: {exc}"

        result = await self._await_child(child.run_id, child.budget)
        self._registry.emit_event(
            self._parent_run_id, "subagent_finished", level="info",
            category="result",
            data={"child_run_id": child.run_id, "status": result[0]},
        )
        status, body, error = result
        if status == "completed":
            return f"[sub-agent {child.run_id} completed]\n{body or '(empty)'}"
        return (
            f"[sub-agent {child.run_id} ended: {status}]"
            + (f" {error}" if error else "")
        )

    async def _await_child(self, child_run_id: str, child_budget: dict):
        """Wait for the child run to finish; return (status, result, error).

        Awaits the child's background task DIRECTLY (no disk-polling): the
        registry holds it in _run_tasks. The wait cap is derived from the
        child's own time_s budget (+ a small margin so the child's cooperative
        time-budget stop fires first) and falls back to a default only when the
        child set no time budget. On timeout we CANCEL the child rather than
        orphan it — otherwise the parent would report 'timed out' while the
        child kept running, emitting events and consuming budget."""
        terminal = ("completed", "failed", "cancelled", "interrupted")
        task = self._registry.get_run_task(child_run_id)

        # Wait cap: child's time_s + margin, else the default backstop. The
        # child enforces its OWN time budget cooperatively; this is just an
        # outer guard so a wedged child can't block the parent forever.
        child_time = (child_budget or {}).get("time_s")
        wait_cap = (child_time + 10.0) if child_time else _DEFAULT_CHILD_WAIT_S

        if task is not None:
            # Wait for the child, but also react PROMPTLY if the PARENT run is
            # cancelled while we're blocked here (Item 37e). Without this, a
            # cancel on the parent wouldn't take effect until this await hit
            # wait_cap (up to _DEFAULT_CHILD_WAIT_S = 300s). We poll the
            # parent's cooperative cancel flag on a short tick and propagate
            # the cancel down to the child, so parent-cancel latency is ~tick,
            # not ~wait_cap.
            parent_control = self._registry.get_control(self._parent_run_id)
            deadline = wait_cap
            tick = 0.1
            # Track elapsed via a monotonic clock, NOT `waited += tick`: under
            # event-loop load each `wait_for(timeout=tick)` can take well over
            # `tick` to raise TimeoutError, so summing ticks under-counts real
            # time and the parent could wait far past `wait_cap` before
            # cancelling a wedged child (Gemini review #3). monotonic() measures
            # actual elapsed regardless of scheduling drift.
            start = time.monotonic()
            shielded = asyncio.shield(task)
            timed_out = False
            while True:
                if parent_control is not None and parent_control.cancel_requested:
                    logger.info(
                        f"parent {self._parent_run_id} cancelled while awaiting "
                        f"sub-agent {child_run_id} — cancelling child"
                    )
                    self._registry.cancel_run(child_run_id)
                    await asyncio.sleep(0.1)  # let the cooperative stop settle
                    break
                try:
                    await asyncio.wait_for(asyncio.shield(shielded), timeout=tick)
                    break  # child finished
                except asyncio.TimeoutError:
                    if time.monotonic() - start >= deadline:
                        timed_out = True
                        break
            if timed_out:
                # Don't orphan the child — cancel it cooperatively, then read
                # whatever terminal state it lands in.
                logger.warning(
                    f"sub-agent {child_run_id} exceeded wait cap {wait_cap}s — cancelling"
                )
                self._registry.cancel_run(child_run_id)
                await asyncio.sleep(0.1)  # let the cooperative stop settle
        else:
            # No task handle (e.g. already finished or test seam) — fall back
            # to a short bounded poll on the persisted meta.
            for _ in range(int(_DEFAULT_CHILD_WAIT_S / 0.05)):
                meta = self._registry.get_run(child_run_id)
                if meta is not None and meta.status in terminal:
                    break
                await asyncio.sleep(0.05)

        meta = self._registry.get_run(child_run_id)
        if meta is not None and meta.status in terminal:
            return meta.status, meta.result, meta.error
        return "interrupted", None, "sub-agent wait timed out"
