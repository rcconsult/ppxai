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

Scope: lifecycle only — but "lifecycle only" is NOT "unpoliced". This module
once said the request-shaped validation "stays in the routes for now" and that
a TUI "passes an already-resolved grant". That sentence was the bug: nothing
resolved or authorized the TUI's grant, so an in-process launch reached the
runner with no tier gate, no shell reject, and raw `--skill` strings mounted
as read roots (docs/archive/branch-review-v1.19.1.md). Admission now lives in
`engine/task_authorizer.py`, and `launch()` takes an `AuthorizedTask` — the
only way to obtain one is to pass `authorize_task()`.
"""

from __future__ import annotations

from typing import Any, Optional

from ..common.logger import get_logger
from .agent_runs import RunMeta, resume_refusal
from .task_authorizer import AuthorizedTask, check_tier_enabled
from .task_runner import build_task_runner, default_run_registry
from .types import Message

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

    The two steps are tracked SEPARATELY and each is marked done only after
    it succeeds, so a transient failure retries on the next dispatch. A single
    flag set BEFORE the work (the shape this replaced) made one failure
    permanent for the life of the process: every later call returned early,
    so orphans stayed unswept and the badge could never light — silently,
    because the failure is logged at debug. Splitting the `try` also matters:
    with both steps inside one, a raising sweep swallowed the change hook in
    the same call. Marking AFTER success keeps the idempotence promise — a
    step that did succeed never runs twice, so hooks cannot stack.
    """
    backend = get_task_backend()
    if session_provider is not None:
        backend._session_provider = session_provider

    if not getattr(backend, "_orphans_swept", False):
        try:
            backend.registry.sweep_orphans()
            backend._orphans_swept = True
        except Exception:  # noqa: BLE001
            # A registry that cannot sweep must not stop the command working;
            # the run surface degrades, it does not disappear. Left unmarked
            # so the next dispatch tries again.
            logger.debug("task backend orphan sweep failed", exc_info=True)

    if on_change is not None and not getattr(backend, "_on_change_wired", False):
        try:
            backend.registry.on_change(on_change)
            backend._on_change_wired = True
        except Exception:  # noqa: BLE001
            logger.debug("task backend on_change wiring failed", exc_info=True)

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
        auth: AuthorizedTask,
        *,
        kind: str = "task",
        owner: Optional[str] = None,
    ) -> RunMeta:
        """Mint a run from an AUTHORIZED task and schedule it.

        Takes an `AuthorizedTask` — not loose kwargs — because that is the only
        way to make "was this authorized?" unanswerable-in-the-negative at this
        seam. The single way to obtain one is
        `task_authorizer.authorize_task()`, which runs the tier gate, the shell
        reject, the tool kill-switches, provider validation, name-only
        spec/skill resolution and the egress ceiling.

        In particular there is deliberately NO `extra_read_paths` parameter.
        Read scope is an OUTPUT of authorization (`auth.read_roots`, resolved
        skill directories confined to `skills_dir`), never a caller input —
        mirroring the HTTP request model, which has no such field either. The
        removed kwarg is what let `--skill /etc` mount an arbitrary directory
        under the filesystem seal.

        Non-blocking by construction: the caller gets a `run_id` it can list,
        watch, cancel or collect. **Needs a live event loop** — see the module
        docstring.

        `allow_spawn` is derived, never passed: a top-level run may spawn only
        when `spawn_subagent` is in its own grant, and a child is always built
        with `allow_spawn=False`. Keeping that derivation here means a caller
        cannot widen depth by asking.
        """
        grant = list(auth.tools)
        meta = self.registry.start_run(
            task=auth.task,
            kind=kind,
            tools=grant,
            provider=auth.provider,
            model=auth.model,
            network=auth.network,
            budget=auth.budget,
            owner=owner,
            hold_result=collect_holds(),
            system=auth.system,
            read_roots=auth.read_roots,
            workdir=auth.workdir,
        )
        runner = build_task_runner(
            self.registry,
            provider_name=auth.provider,
            model=auth.model,
            task=auth.task,
            tools=grant,
            allow_outbound=list(auth.network or []),
            allow_spawn="spawn_subagent" in grant,
            system=auth.system,
            extra_read_paths=auth.read_roots,
            workdir=auth.workdir,
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

    def auto_merge_if_configured(self, run_id: str) -> tuple[bool, str, bool]:
        """Merge a terminal run without an explicit `collect`, under "auto".

        Mirrors the web client's `_autoMergeIfConfigured`, which fires on the
        watcher's terminal render. Under "yes" the result is HELD and the user
        collects it; under "auto" nothing holds it, so the watcher is the only
        thing that can put it in the conversation.

        Returns `(merged, reason, retryable)`.

        **`retryable` is why this returns three values.** A `False` here means
        two very different things, and a caller that conflates them breaks in
        one of two ways: treat every `False` as final and a transient failure
        silently DROPS the run's result forever; treat every `False` as
        retryable and a decided run is re-attempted on every poll for the life
        of the process — which is the *default* config, since `collect: "yes"`
        makes "not in auto mode" the normal answer.

        - **Decided** (`retryable=False`): not in auto mode, collect disabled,
          unknown run, no result to merge. Nothing about polling again changes
          these.
        - **Transient** (`retryable=True`): no active session yet, or the
          collect mode was momentarily unreadable. The precondition can arrive
          later.

        Session availability is checked HERE rather than inferred from
        `merge_result`'s reason text: it is the one precondition that can
        change between polls, and classifying it by string-matching a message
        would break the moment that message is reworded.
        """
        from ..config.execution import get_execution_collect

        try:
            if get_execution_collect() != "auto":
                return False, "not in auto mode", False
        except Exception:  # noqa: BLE001
            return False, "collect mode unreadable", True
        if self._session_provider is None or self._session_provider() is None:
            return False, "no active session", True
        ok, reason = self.merge_result(run_id)
        return ok, reason, False

    def resume(self, run_id: str) -> tuple[bool, str]:
        """Resume an interrupted run (T7). Returns `(ok, reason)`.

        `registry.resume_run` takes `(meta, runner)`, not a run id — resume
        REBUILDS the scoped runner from the run's PERSISTED inputs (task,
        grant, network, system, read roots, workdir) so the resumed run
        executes under the same sandbox the original did. Rebuilding from
        anything else would silently re-scope a run mid-flight.

        `workdir` comes from the meta on purpose: a resume continues where the
        run actually ran, not where this process happens to be.

        Resume is a SECOND admission path — it starts tool-capable execution
        from a persisted grant without going through `authorize_task`. So it
        re-checks the tier gate explicitly, exactly as the HTTP resume route
        does: an operator who switched the tier off must not be able to
        restart a tool-capable run that predates the switch.
        """
        meta = self.registry.get_run(run_id)
        if meta is None:
            return False, f"unknown run_id: {run_id!r}"
        if getattr(meta, "kind", "task") == "task":
            try:
                check_tier_enabled()
            except Exception as exc:
                return False, getattr(exc, "detail", str(exc))
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
