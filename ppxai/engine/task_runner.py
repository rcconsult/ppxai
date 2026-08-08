"""Engine-level builder for a tool-capable sandboxed run.

Extracted from `server/routes/agent_v1.py` in v1.19.1. Nothing about it was
ever HTTP-shaped — it constructs an `EngineClient`, a `ScopedToolManager`
(AC-1 grant), a `NetworkPolicy` (AC-2 egress) and the Inc-6 budget/cancel
control, and never touches a request. It lived in a route module only because
that is where it was first written.

Moving it makes the runner usable **in-process, with no HTTP server**, which
is what the TUIs need for the `/task` port (plan T8b) and what ppxai-sre needs
to embed the runtime.

**The patch point is `ppxai.engine.task_runner.build_task_runner`.**
This matters and is easy to get wrong. The builder passes ITSELF as
`runner_builder=` when registering `spawn_subagent`, so a child run is built
by the same builder; that reference is a module global resolved at call time
from THIS module's namespace. Every caller therefore reaches it through the
module attribute (`task_runner.build_task_runner(...)`) rather than a
from-import binding, so a single patch here redirects top-level AND child
construction.

`agent_v1.build_task_runner` still exists as an import alias for source
compatibility, but **patching that name has no effect** — it is a second
binding to the same object, and rebinding it changes nothing this module
resolves. `tests/test_runner_builder_patch_point.py` pins the behaviour.

Intercepting child-run construction is how ppxai-sre applies its PolicyEngine
to spawned children, so this is a supported integration surface, not an
internal detail.
"""

from __future__ import annotations

import os
import time
from typing import Any, Dict, List, Optional, Protocol, Union

from ..config.execution import get_execution_task_config
from ..config.paths import get_default_working_dir
from .agent_scoped_tools import ScopedToolManager
from .client import EngineClient
from .tools.agent_spawn import SpawnSubagentTool
from .tools.filesystem_policy import build_filesystem_policy
from .tools.network_policy import NetworkPolicy
from .types import EventType

# An egress allowlist entry is either a bare host ("example.com", any path) or
# a scoped mapping {"host": ..., "paths": [...]}. Typed here because the
# element shape was previously implicit in a bare `list`.
EgressEntry = Union[str, Dict[str, Any]]


class RunMetaLike(Protocol):
    """What `build_task_runner`'s own body reads off the run meta.

    **Incomplete on purpose, and dangerous to read as complete.** These two
    attributes are what THIS module touches. But `m` is also passed WHOLE and
    opaque into `registry.park_run(m, ...)`, which is typed to the concrete
    `RunMeta` and MUTATES it — flipping status, writing `meta.waiting` and
    checkpointing `state.json`.

    So the real contract is "satisfies these attributes AND whatever the
    registry demands of it". A duck object matching only this Protocol will
    type-check and then fail at runtime the first time a spawn needs consent.
    Pass a meta from the same family as the registry you pass.
    """

    run_id: str
    owner: Optional[str]


class TaskRunRegistry(Protocol):
    """The three registry methods this builder uses. Pinned so a substitute
    implementation is a supported move rather than reverse-engineering.

    Small on purpose: implementing three methods is cheaper than adopting the
    concrete registry, and these three are exactly where an integrator wants
    to sit. `emit_event` is where `network_policy_denied` becomes an audit
    record; `park_run` is where a spawn-consent park becomes a policy
    decision requiring approval.

    See `RunMetaLike` — a substitute registry must accept the meta objects it
    is handed.
    """

    def emit_event(self, run_id: str, event: str, *, level: str = "info",
                   category: str = "", data: Optional[dict] = None) -> None: ...

    async def park_run(self, meta: Any, *, kind: str, prompt: str,
                       ttl_s: float, data: Optional[dict] = None) -> dict: ...

    def get_control(self, run_id: str) -> Any: ...


def default_run_registry():
    """Build a registry over the standard `<PPXAI_HOME>/runs/` filesystem store.

    Exists so that path is resolved in ONE place. It was previously inlined in
    `server/state.py`, and that directory is part of the
    `runs/<run_id>/agent-<n>/` namespace named on the ppxai-sre seam — two
    independent resolutions of a load-bearing path is how it drifts.

    Deliberately NOT placed in `engine/agent_runs.py`: that module imports
    only `common.logger`, which is what lets `RunMeta` be read off disk
    without booting an engine. Adding `config.loader` there would drag the
    config stack into every meta read.

    Returns a bare registry — no orphan sweep, no change hooks. Those are
    lifecycle concerns of whoever owns the process; `server/state.py` layers
    them on top.
    """
    from ..config.loader import PPXAI_HOME
    from .agent_runs import AgentRunRegistry, FilesystemAgentRunStore

    return AgentRunRegistry(FilesystemAgentRunStore(PPXAI_HOME / "runs"))


DEFAULT_AGENT_SYSTEM_PROMPT = (
    "You are an autonomous agent executing a single bounded task. "
    "Use ONLY the tools you have been granted to accomplish it — do not ask "
    "the user for input, and do not fall back to any native capability "
    "(e.g. built-in web search) when a granted tool covers the need. "
    "When you need an action, emit a tool call in the required format rather "
    "than describing what you would do. Work within your capability grant and "
    "egress allowlist; if the task cannot be done with the granted tools, say "
    "so plainly and stop. Be concise; report results, not intentions."
)


def compose_agent_system_prompt(caller_system: Optional[str]) -> str:
    """Build the /task engine system prompt: the bounded-agent default, plus
    the caller-supplied `system` (rendered AGENT.md / persona) when present.

    The caller's instructions come SECOND so they refine/extend the base
    framing (identity, role, boundaries) without losing the
    use-only-granted-tools guarantee. Returns the default alone when the
    caller passes nothing."""
    base = DEFAULT_AGENT_SYSTEM_PROMPT
    extra = (caller_system or "").strip()
    return f"{base}\n\n{extra}" if extra else base


def build_task_runner(
    registry: TaskRunRegistry,
    *,
    provider_name: str,
    model: str,
    task: str,
    tools: list[str],
    allow_outbound: List[EgressEntry],
    allow_spawn: bool = False,
    system: Optional[str] = None,
    extra_read_paths: Optional[List[str]] = None,
    workdir: Optional[str] = None,
):
    """Build the async runner that drives a tool-capable run (Inc 4–7).

    Shared by `/v1/agent/task` (top-level) and the `spawn_subagent` tool
    (child run) so both go through the IDENTICAL sandbox: ScopedToolManager
    (AC-1 grant), NetworkPolicy (AC-2 egress), and Inc 6 budget/cancel
    control. The runner is a function of explicit params, not the request, so
    a child run can be built with its own (subset) grant + allowlist.

    allow_spawn gates depth: a top-level run gets the `spawn_subagent` tool
    registered IF it's in the grant; a child run is always built with
    allow_spawn=False, so it can never spawn — enforcing the N=1 / depth=1
    rule structurally (a grandchild is impossible).

    extra_read_paths (T4): additional read roots mounted into this run's
    read-scope on TOP of the static sandbox `read_paths.allow` — the `--skill`
    directories. Only consulted when the filesystem seal is engaged
    (enforcement="in_process"); ignored otherwise (nothing to enforce).

    workdir (v1.19.x): the run's working directory as per-run intent, applied
    only when the seal is OFF (the sealed branch always uses the per-run
    jail). None → the server default (server.working_dir config, else home) —
    deliberately NEVER the process launch dir, which made a run's relative
    paths depend on how the operator happened to start the server.
    """
    async def _runner(m) -> str:
        engine = EngineClient()
        engine.set_provider(provider_name)
        engine.set_model(model)
        engine.enable_tools()  # registers builtins + sets tool-loop limits
        # v1.19.x: bounded-agent framing (+ caller's rendered AGENT.md via
        # `system`) REPLACES the provider's chat system_prompt for this run, so
        # the model uses granted tools instead of native fallbacks. Set on this
        # per-run engine only (D1 isolation) — never touches other sessions.
        engine.system_prompt_override = compose_agent_system_prompt(system)

        # Inc 7: register spawn_subagent ONLY for a top-level run whose grant
        # includes it. A child run (allow_spawn=False) never gets the tool, so
        # depth is capped at 1 structurally — not by a runtime check the model
        # could probe. The tool carries this run as the parent context and
        # enforces child grant ⊆ this grant, child egress ⊆ this allowlist.
        if allow_spawn and "spawn_subagent" in tools:
            # T5: the interactive consent channel over /v1/agent/task. A spawn
            # that needs consent PARKS the run (`waiting{consent}` + an
            # AGENT_WAITING event carrying the resume token) and blocks right
            # here until POST /v1/agent/runs/{id}/respond answers it — or the
            # consent TTL expires, which resolves to a denial (fail-closed).
            # This replaces the pre-T5 adapter that routed to the engine's
            # shell-consent (which had no UI over HTTP and auto-denied).
            async def _spawn_consent(summary: str) -> bool:
                ttl = float(
                    get_execution_task_config()["consent"]["consent_ttl_s"]
                )
                response = await registry.park_run(
                    m, kind="consent", prompt=summary, ttl_s=ttl,
                )
                return response.get("approved") is True

            # Server-context spawn consent policy
            # (execution.task.consent.spawn_consent):
            # "deny" (default, safe) — a spawn parks for interactive consent as
            # above, denying on TTL timeout; "auto" — skip the park entirely
            # (subset rules remain the boundary).
            spawn_consent = get_execution_task_config()["consent"]["spawn_consent"]
            engine.tool_manager.register_tool(SpawnSubagentTool(
                registry=registry,
                parent_run_id=m.run_id,
                parent_owner=getattr(m, "owner", None),
                parent_tools=list(tools),
                parent_allow_outbound=list(allow_outbound),
                parent_provider=provider_name,
                parent_model=model,
                parent_workdir=workdir,  # child resolves paths where the parent does
                request_consent=_spawn_consent,
                consent_policy=spawn_consent,
                runner_builder=build_task_runner,
            ))

        def _on_deny(name: str) -> None:
            registry.emit_event(
                m.run_id, "tool_denied", level="warning", category="tool",
                data={"tool": name, "grant": list(tools)},
            )

        # AC-2: per-run egress allowlist. Always installed for a tool-capable
        # run — even with no `network` spec, so a granted network tool is
        # deny-by-default (fail-closed). on_network emits the typed audit event.
        # Step ④: the run's provider context rides on the policy so the
        # egress chokepoint resolves per-provider backend tuples with the
        # SAME answer the call-time chain uses.
        net_policy = NetworkPolicy(allow_outbound, provider_name=provider_name)

        def _on_network(allowed: bool, payload: dict) -> None:
            payload = {**payload, "run_id": m.run_id}
            registry.emit_event(
                m.run_id,
                "network_policy_allowed" if allowed else "network_policy_denied",
                level="info" if allowed else "warning",
                category="network",
                data=payload,
            )

        # T2: filesystem SEAL (tools.agent.sandbox, enforcement="in_process").
        # Off by default — engaged only when the operator opts in. When on, the
        # run gets a per-run workdir (its ONLY writable root), relative paths
        # resolve there, and reads/writes are confined by FilesystemPolicy.
        fs_policy = None
        _on_path = None
        sandbox = get_execution_task_config()["sandbox"]
        if sandbox.get("enforcement") == "in_process":
            jail_workdir = os.path.join(
                os.path.expanduser(sandbox["workdir"]["root"]), m.run_id, "work"
            )
            os.makedirs(jail_workdir, exist_ok=True)
            engine.set_working_dir(jail_workdir)  # relative tool paths resolve here
            fs_policy = build_filesystem_policy(
                sandbox, jail_workdir, extra_read_paths=extra_read_paths
            )

            def _on_path(allowed: bool, payload: dict) -> None:  # noqa: F811
                # Allowed reads are silent (they'd fire on every read); only the
                # denial is a security-relevant event.
                if not allowed:
                    registry.emit_event(
                        m.run_id, "path_denied", level="warning",
                        category="filesystem", data={**payload, "run_id": m.run_id},
                    )
        else:
            # Seal OFF: apply the per-run workdir intent, else the server
            # default — never the process launch dir (v1.19.x
            # workdir-alignment; a resume whose recorded workdir has since
            # vanished falls back to the default rather than aiming tools at
            # a dead path).
            effective_wd = workdir
            if effective_wd and not os.path.isdir(effective_wd):
                effective_wd = None
            engine.set_working_dir(effective_wd or get_default_working_dir())

        engine.tool_manager = ScopedToolManager(
            engine.tool_manager, list(tools), on_deny=_on_deny,
            network_policy=net_policy, on_network=_on_network,
            filesystem_policy=fs_policy, on_path=_on_path,
        )

        # Item 50: a grant naming a tool that does not exist is always a caller
        # mistake — the model is silently offered fewer tools than intended and
        # the run fails later for an invisible reason. This is checked HERE
        # (not at request validation) because only now is the fully-registered
        # base manager available: editor/shell/container/display tools register
        # solely when an engine exists, so a registry rebuilt without one would
        # report a misleading subset and falsely reject valid names.
        unresolved_msg = engine.tool_manager.unresolved_grant_message()
        if unresolved_msg:
            registry.emit_event(
                m.run_id, "grant_unresolved", level="warning", category="tool",
                data={"unresolved": engine.tool_manager.unresolved_grant(),
                      "grant": list(tools)},
            )
            raise ValueError(unresolved_msg)

        # Inc 6: cooperative budget/cancel control. Polled at each tool-loop
        # boundary (on TOOL_CALL) so a cap or cancel stops the run at a clean
        # checkpoint — never mid-tool-call. control.check() raises RunCancelled
        # / RunBudgetExceeded, which run_in_background maps to the right status.
        control = registry.get_control(m.run_id)

        final_text: list[str] = []
        async for event in engine.chat(task, stream=False):
            # Surface tool activity on the run's event stream. The engine's
            # TOOL_CALL carries the name in event.data["tool"] (a dict), not
            # in metadata; STREAM_END carries the final text as event.data,
            # which is a plain string (sometimes a dict with "content").
            if event.type == EventType.TOOL_CALL:
                if control is not None:
                    # Refresh the run's cumulative token total from the engine
                    # before checking, so the token budget is actually enforced
                    # (not just iterations/time). Read session.live_run_tokens —
                    # the LIVE in-flight total chat_with_tools bumps per tool
                    # iteration. (session.usage.total_tokens is only committed at
                    # terminal STREAM_END, so it's stale/0 mid-run — reading it
                    # left the token axis silently unenforced; v1.19.0 fix.) This
                    # EngineClient is run-local (D1: one per run), so the live
                    # total IS this run's total. check() runs BEFORE counting this
                    # iteration: a budget of N lets N iterations run, stops at the
                    # (N+1)th.
                    try:
                        control.tokens_used = engine.session.live_run_tokens
                    except AttributeError:
                        pass  # usage not available — leave token axis unenforced
                    control.check(now=time.monotonic())
                    control.iterations += 1
                d = event.data or {}
                name = d.get("tool", "") if isinstance(d, dict) else ""
                # F4: carry a truncated args snapshot on the audit event —
                # what the model actually asked the tool to do (e.g. the
                # web_search query). Values clamped so a large file-write
                # arg can't bloat events.jsonl.
                raw_args = d.get("arguments") if isinstance(d, dict) else None
                args_snapshot = {
                    str(k): str(v)[:200] for k, v in raw_args.items()
                } if isinstance(raw_args, dict) else None
                registry.emit_event(
                    m.run_id, "tool_call", level="debug", category="tool",
                    data={"tool": name, "arguments": args_snapshot},
                )
            elif event.type in (EventType.ERROR, EventType.PROVIDER_THROTTLED):
                # The engine reports provider/config failures as EVENTS, not
                # exceptions — chat() yields ERROR ("No provider", auth, network)
                # or PROVIDER_THROTTLED (429/403) and returns normally. If we
                # only watched STREAM_END, run_in_background would see a clean
                # return and mark the run COMPLETED with an empty result. Raise
                # so the run finishes FAILED with the provider's message.
                d = event.data
                msg = d.get("message") if isinstance(d, dict) else str(d)
                raise RuntimeError(
                    f"{event.type.value}: {msg or 'provider call failed'}"
                )
            elif event.type == EventType.STREAM_END and event.data is not None:
                d = event.data
                text = d.get("content", "") if isinstance(d, dict) else str(d)
                if text:
                    final_text.append(text)

        # F4: persist the run's OWN usage on its audit trail. This engine is
        # run-local (D1), so session.usage is per-run attribution by
        # construction — the seam ADR 0008's cross-tier sink will read.
        try:
            u = engine.session.usage
            ws = (u.tool_calls or {}).get("web_search")
            registry.emit_event(
                m.run_id, "run_usage", level="debug", category="result",
                data={
                    "prompt_tokens": u.prompt_tokens,
                    "completion_tokens": u.completion_tokens,
                    "total_tokens": u.total_tokens,
                    "estimated_cost": u.estimated_cost,
                    "web_search": {
                        "call_count": ws.call_count,
                        "estimated_cost": ws.estimated_cost,
                        "backend": ws.provider,
                    } if ws else None,
                },
            )
        except Exception:  # noqa: BLE001 — usage audit must never fail a run
            pass
        return "\n".join(final_text)

    return _runner
