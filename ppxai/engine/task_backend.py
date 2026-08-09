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

from .agent_runs import RunMeta, resume_refusal
from .task_runner import build_task_runner, default_run_registry


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


class InProcessTaskBackend:
    """Verb-for-verb peer of the web client's `/v1/agent/*` slice.

    Method names mirror the run lifecycle rather than the HTTP paths, but the
    semantics are the route's: `launch` mints and schedules, results are HELD
    when `execution.collect` says so, `collect` finalizes a held result, and a
    parked run is answered through `respond`.
    """

    def __init__(self, registry=None):
        """`registry` defaults to the standard `<PPXAI_HOME>/runs/` store.

        Injectable so a caller (tests, ppxai-sre) can supply its own — the
        same three-method surface `TaskRunRegistry` pins.
        """
        self.registry = registry if registry is not None else default_run_registry()

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

    def collect(self, run_id: str) -> tuple[bool, str]:
        """Finalize a held result (T6). `ack_run` is the registry's name."""
        return self.registry.ack_run(run_id)

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
