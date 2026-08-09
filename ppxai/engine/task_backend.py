"""In-process `/task` · `/run` backend — the embed half of T8b.

The web and VSCode clients drive the run lifecycle over `/v1/agent/*`. The
TUIs have **no channel to a ppxai-server**, which is the transport decision
recorded in `docs/plan-task-command-sequencing.md` §T8b. We took *embed*: this
module is the same verb surface, in-process, over the same registry and the
same `build_task_runner` sandbox — so a TUI is a peer of the HTTP clients
rather than a reimplementation of them.

**Requires a running asyncio event loop.** `registry.run_in_background()`
schedules an `asyncio.Task` and returns immediately; without a live loop the
run is created and then never advances. Textual owns a loop for its whole
lifetime, so it satisfies this natively. The Rich TUI does **not** — its
prompt is a blocking `session.prompt()` and each operation spins a throwaway
`asyncio.run()`, so a run could only progress while the user is not at the
prompt. That is the open half of T8b and needs an explicit decision (async
main loop, or a blocking variant of `launch`), not a silent workaround.

Scope: lifecycle only. The request-shaped validation in the routes — grant
merge across request/spec/skills, egress ceiling, provider 400s — stays there
for now. A TUI caller passes an already-resolved grant.
"""

from __future__ import annotations

from typing import Any, Optional

from ..common.logger import get_logger
from .agent_runs import RunMeta, resume_refusal
from .task_runner import build_task_runner, default_run_registry

logger = get_logger("engine")


def collect_holds() -> bool:
    """Does `execution.collect` map to a T6 hold at launch? (U4, ADR 0011)

    `"yes"` → held until collected; `"auto"`/`"no"` → auto-finalize. Config
    errors fall back to the shipped default (`"yes"`).

    Canonical copy. `agent_v1._collect_holds` previously owned this and is a
    route module, so an in-process caller could not reach it without importing
    the server layer — the same trap that made `get_default_working_dir` and
    `compose_agent_system_prompt` block the runner extraction.
    """
    from ..config.execution import get_execution_collect

    try:
        return get_execution_collect() == "yes"
    except Exception:  # noqa: BLE001 — a config error must not block a launch
        return True


_shared: Optional["InProcessTaskBackend"] = None


def configure_task_backend(session_provider=None, on_change=None):
    """Layer the lifecycle concerns onto the process-wide backend.

    `default_run_registry()` is deliberately bare — its docstring says the
    sweep and the change hooks belong to "whoever owns the process".
    `server/state.py:204-217` owns one and layers them on. T8b made the TUI
    own one too, and layered nothing; this is that missing half.

    Both steps mirror the server exactly:

    * **`sweep_orphans()`** — a fresh registry means a fresh process, so any
      run still marked pending/running/waiting on disk was orphaned by the
      last shutdown (its task, control and consent future died with it).
      Landing them `interrupted` is what makes `ls` tell the truth and
      `resume` able to pick them up. Without it a run killed with the TUI
      shows `running` forever.
    * **`on_change`** — the hook that writes `AppState.background_agents`.
      `tui/app.py:254` already SUBSCRIBES to that key and renders a badge;
      its comment says "the server mirrors" it, which is true over HTTP and
      false in-process. Without this the badge can never light.

    Idempotent: called on every `/task`/`/run` dispatch, so it must not sweep
    repeatedly or stack hooks.
    """
    backend = get_task_backend()
    if session_provider is not None:
        backend._session_provider = session_provider
    if getattr(backend, "_lifecycle_wired", False):
        return backend
    backend._lifecycle_wired = True
    try:
        backend.registry.sweep_orphans()
        if on_change is not None:
            backend.registry.on_change(on_change)
    except Exception:  # noqa: BLE001
        # A registry that cannot sweep must not stop the command working;
        # the run surface degrades, it does not disappear.
        logger.debug("task backend lifecycle wiring failed", exc_info=True)
    return backend


def get_task_backend() -> "InProcessTaskBackend":
    """Process-wide backend singleton.

    **Must be shared, not constructed per call.** `default_run_registry()`
    builds a NEW registry each time, and a registry carries in-memory state
    the filesystem store does not: the cooperative `RunControl` per run, the
    background `asyncio.Task` handles, and event subscribers. Two registries
    over the same directory would agree about persisted meta and disagree
    about everything live — `cancel` would find no control for a run another
    instance launched, and a watcher would never receive its events.

    Intended for in-process clients (the TUIs). The server does NOT use this:
    it owns its own registry singleton in `server/state.py`, which layers on
    the orphan sweep and the AppState mirror hook.
    """
    global _shared
    if _shared is None:
        _shared = InProcessTaskBackend()
    return _shared


class InProcessTaskBackend:
    """Verb-for-verb peer of the web client's `/v1/agent/*` slice.

    Method names mirror the run lifecycle rather than the HTTP paths, but the
    semantics are the route's: `launch` mints and schedules, results are HELD
    when `execution.collect` says so, `collect` finalizes a held result, and a
    parked run is answered through `respond`.
    """

    def __init__(self, registry=None, session_provider=None):
        """`registry` defaults to the standard `<PPXAI_HOME>/runs/` store.

        Injectable so a caller (tests, ppxai-sre) can supply its own — the
        same three-method surface `TaskRunRegistry` pins.

        `session_provider` is a zero-arg callable returning the client's
        ACTIVE session. It is how a run's result reaches the conversation
        (U4): the HTTP clients POST /sessions/merge-run-result and the route
        appends to `s.engine.session`, but an in-process client has no
        request to hang that off. Without it, `collect` finalizes the run and
        the result never enters the session — which is what made every TUI
        session message-less and left session restore with nothing to
        restore.
        """
        self.registry = registry if registry is not None else default_run_registry()
        self._session_provider = session_provider

    # ── launch ──────────────────────────────────────────────────────────────

    def launch(
        self,
        task: str,
        *,
        kind: str = "task",
        tools: Optional[list[str]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        network: Optional[list] = None,
        budget: Optional[dict] = None,
        system: Optional[str] = None,
        workdir: Optional[str] = None,
        extra_read_paths: Optional[list[str]] = None,
        owner: Optional[str] = None,
    ) -> RunMeta:
        """Mint a run and schedule it. Returns immediately with its meta.

        Non-blocking by construction: the caller gets a `run_id` it can list,
        watch, cancel or collect. **Needs a live event loop** — see the module
        docstring.

        `allow_spawn` is derived, never passed: a top-level run may spawn only
        when `spawn_subagent` is in its own grant, and a child is always built
        with `allow_spawn=False`. Keeping that derivation here means a caller
        cannot widen depth by asking.
        """
        grant = list(tools or [])
        meta = self.registry.start_run(
            task=task,
            kind=kind,
            tools=grant,
            provider=provider,
            model=model,
            network=network,
            budget=budget,
            owner=owner,
            hold_result=collect_holds(),
            system=system,
            read_roots=extra_read_paths,
            workdir=workdir,
        )
        runner = build_task_runner(
            self.registry,
            provider_name=provider,
            model=model,
            task=task,
            tools=grant,
            allow_outbound=list(network or []),
            allow_spawn="spawn_subagent" in grant,
            system=system,
            extra_read_paths=extra_read_paths,
            workdir=workdir,
        )
        self.registry.run_in_background(meta, runner)
        return meta

    # ── observe ─────────────────────────────────────────────────────────────

    def list_runs(self, kind: Optional[str] = None) -> list[RunMeta]:
        """All runs, newest-first per the registry, optionally kind-filtered.

        `/task ls` shows `kind="task"`, `/run ls` shows `kind="oneshot"` —
        the same split the web clients apply (U3).
        """
        runs = self.registry.list_runs()
        if kind is None:
            return runs
        return [r for r in runs if getattr(r, "kind", None) == kind]

    def get_run(self, run_id: str) -> Optional[RunMeta]:
        return self.registry.get_run(run_id)

    def events(self, run_id: str, **kwargs) -> list:
        return self.registry.read_events(run_id, **kwargs)

    def subscribe(self, run_id: str):
        """Live event queue — the in-process analogue of the SSE channel.

        Pair every call with `unsubscribe`, or the registry keeps feeding a
        queue nobody drains.
        """
        return self.registry.subscribe(run_id)

    def unsubscribe(self, run_id: str, queue) -> None:
        self.registry.unsubscribe(run_id, queue)

    # ── act ─────────────────────────────────────────────────────────────────

    def cancel(self, run_id: str) -> bool:
        return self.registry.cancel_run(run_id)

    def respond(self, run_id: str, token: str, approved: bool,
                text: Optional[str] = None) -> Any:
        """Answer a parked run (T5). The token comes from `meta.waiting`.

        A wrong or stale token is refused by the registry rather than
        silently accepted — consent must not be answerable by guessing.
        """
        return self.registry.respond_run(
            run_id, token=token, approved=approved, text=text
        )

    def merge_result(self, run_id: str) -> tuple[bool, str]:
        """U4 (ADR 0011): plain-merge a run's result into the active session.

        The in-process equivalent of `POST /sessions/merge-run-result`, and
        deliberately the same semantics — the run enters the conversation as a
        plain `user(task)` → `assistant(result)` exchange, no provenance
        tagging, no special block type.

        **The PAIR is load-bearing.** `validate_and_fix_alternation` drops a
        leading assistant message and collapses same-role neighbours, so a
        lone merged message of either role can silently vanish from the next
        provider request — caught live in the U4 trial, where the model
        answered "no passphrase appeared" while the merge sat dropped. Both
        messages or neither.

        Refused under `execution.collect="no"` with the same wording the
        clients surface, so a user who disabled collect is told, rather than
        watching a result disappear.
        """
        from ..config.execution import get_execution_collect
        from .types import Message

        try:
            if get_execution_collect() == "no":
                return False, (
                    'Collect is disabled (execution.collect="no"). Set '
                    'execution.collect to "yes" or "auto" in '
                    "ppxai-config.json to enable merging run results."
                )
        except Exception:  # noqa: BLE001 — a config error must not eat a result
            pass

        if self._session_provider is None:
            return False, "no session to merge into"
        session = self._session_provider()
        if session is None:
            return False, "no active session"

        meta = self.registry.get_run(run_id)
        if meta is None:
            return False, f"unknown run: {run_id}"
        result = getattr(meta, "result", None)
        if not result:
            return False, f"run {run_id} has no result to merge"

        session.add_message(Message(role="user", content=meta.task))
        session.add_message(Message(role="assistant", content=result))
        return True, f"merged {len(result)} chars"

    def collect(self, run_id: str) -> tuple[bool, str]:
        """Finalize a held result (T6) AND merge it into the session (U4).

        Two steps, matching what both HTTP clients do —
        `agent-run-controller.js:121` and `taskController.ts:596` each ack and
        then merge. Doing only the first leaves the run finalized and the
        conversation unchanged, which is the shape of the T8b regression.
        """
        ok, reason = self.registry.ack_run(run_id)
        if ok:
            merged, detail = self.merge_result(run_id)
            if not merged:
                # The run IS collected; only the merge failed. Say so rather
                # than reporting success and losing the result silently.
                return True, f"collected (not merged: {detail})"
        return ok, reason

    def auto_merge_if_configured(self, run_id: str) -> tuple[bool, str]:
        """Merge a terminal run without an explicit `collect`, under "auto".

        Mirrors the web client's `_autoMergeIfConfigured`, which fires on the
        watcher's terminal render. Under "yes" the result is HELD and the user
        collects it; under "auto" nothing holds it, so the watcher is the only
        thing that can put it in the conversation.
        """
        from ..config.execution import get_execution_collect

        try:
            if get_execution_collect() != "auto":
                return False, "not in auto mode"
        except Exception:  # noqa: BLE001
            return False, "collect mode unreadable"
        return self.merge_result(run_id)

    def resume(self, run_id: str) -> tuple[bool, str]:
        """Resume an interrupted run (T7). Returns `(ok, reason)`.

        `registry.resume_run` takes `(meta, runner)`, not a run id — resume
        REBUILDS the scoped runner from the run's PERSISTED inputs (task,
        grant, network, system, read roots, workdir) so the resumed run
        executes under the same sandbox the original did. Rebuilding from
        anything else would silently re-scope a run mid-flight.

        `workdir` comes from the meta on purpose: a resume continues where the
        run actually ran, not where this process happens to be.
        """
        meta = self.registry.get_run(run_id)
        if meta is None:
            return False, f"unknown run_id: {run_id!r}"
        refusal = resume_refusal(
            meta, in_flight=self.registry.get_run_task(run_id) is not None
        )
        if refusal is not None:
            # Same refusal contract the route surfaces as 409 — a checkpoint
            # that isn't conclusive must not be resumed into a second run.
            return False, refusal
        runner = build_task_runner(
            self.registry,
            provider_name=meta.provider,
            model=meta.model,
            task=meta.task,
            tools=list(meta.tools),
            allow_outbound=list(getattr(meta, "network", []) or []),
            allow_spawn=True,  # same shape as a fresh top-level task run
            system=getattr(meta, "system", None),
            extra_read_paths=list(getattr(meta, "read_roots", []) or []),
            workdir=getattr(meta, "workdir", None),
        )
        self.registry.resume_run(meta, runner)
        return True, "running"
