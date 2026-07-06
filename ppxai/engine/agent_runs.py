"""Agent run registry — durable, addressable agent runs (ADR 0003 Stage 2).

This is the keystone of the agent platform. An *agent run* is a single
`chat_with_tools` invocation (per ADR 0003 Question A → A1: no outer
continuation loop) that is given a `run_id`, persisted under
`~/.ppxai/runs/<run_id>/agent-<n>/` (the ADR 0005 Inspection Triplet
path), and made addressable + queryable through the registry API.

Layering (ADR 0003 §"Question B" + debt Item 35 — shape the seam now,
defer the abstraction):

    AgentRunRegistry        service: mint run_id, lifecycle, queries
        │ depends on
        ▼
    AgentRunStore           Protocol: the persistence contract
        │ implemented by
        ▼
    FilesystemAgentRunStore concrete (Inc 1). A SQLite / mem0 / vector
                            store is a future Item 35 impl behind the same
                            Protocol — no registry change.

**Increment 1 scope (intentionally minimal — interfaces grow additively
over later increments):** create a run, persist its `meta.json`, list
runs, fetch one. NO background execution (the run executes synchronously
in the caller for now — Inc 2 moves it to an `asyncio.Task`), NO
events.jsonl / state.json (Inc 2-3), NO capability enforcement (Inc 4),
NO budgets / cancel / sub-agents (Inc 5+). The `AgentRunStore` Protocol
exposes only the three methods Inc 1 uses; later increments ADD methods
(`append_event`, `load_state`, …) to the same contract.
"""

from __future__ import annotations

import asyncio
import json
import os
import secrets
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Protocol

from ..common.logger import get_logger

logger = get_logger("tui")


# ---------------------------------------------------------------------------
# Run record (the value — a marshallable dataclass, like SessionMeta)
# ---------------------------------------------------------------------------


@dataclass
class RunMeta:
    """Persisted metadata for one agent run (`meta.json`).

    The on-disk shape. Fields are additive across increments: removing or
    repurposing one is a breaking change, adding an optional one is not
    (same discipline as the v1 wire contract). `run_id` + `agent_n`
    together address a run slot: `runs/<run_id>/agent-<agent_n>/`.
    """

    run_id: str
    task: str
    # pending | running | waiting | cancelling | completed | failed |
    # cancelled | interrupted (Inc 6 adds cancelling/cancelled/interrupted;
    # T5 adds waiting — parked alive on a resume token, see park_run)
    status: str = "pending"
    agent_n: int = 0  # slot index; 0 = top-level run, >0 = sub-agents (Inc 7)
    parent_run_id: Optional[str] = None  # set for sub-agents (Inc 7)
    owner: Optional[str] = None  # Inc 8b: principal that created the run; per-run authz scopes reads to it. None = unowned (created while auth disabled, or a sub-agent) — readable by any authenticated caller.
    provider: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = field(default_factory=list)  # the grant (enforced in Inc 4)
    network: list = field(default_factory=list)  # egress allow_outbound (enforced in Inc 5); provenance/audit on disk
    budget: dict = field(default_factory=dict)  # Inc 6: {tokens?, time_s?, iterations?} caps; absent key = no cap on that axis
    resumable: bool = False  # Inc 6: True when a non-terminal stop (cancel/interrupt) left state a future resume could pick up
    # T5: consent-park context while status == "waiting", else None.
    # {kind, prompt, token, since, expires_at, ttl_s} — the token is the
    # resume credential POST .../respond must present (owner-scoped reads
    # only, so exposing it on the meta is deliberate: the owner IS the
    # principal allowed to answer).
    waiting: Optional[dict] = None
    created_at: float = 0.0
    started_at: Optional[float] = None  # set when execution begins (Inc 2 background)
    finished_at: Optional[float] = None
    result: Optional[str] = None  # synchronous result body (Inc 1); refs in Inc 5
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunMeta":
        # Tolerate unknown keys from a newer writer (forward-compat read):
        # keep only declared fields so an older reader doesn't crash.
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})


# ---------------------------------------------------------------------------
# Run events (Inc 3) — the events.jsonl record, ADR 0003 §11a
# ---------------------------------------------------------------------------

# Severity axis. Ordered so min_level filtering is a simple index compare.
LEVELS = ("debug", "info", "warning", "error")
_LEVEL_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}

# Kind axis. lifecycle = run start/complete/status; tool = tool calls;
# network = egress policy (Inc 5); consent = WAITING/consent (Inc 6+);
# result = AGENT_RESULT_READY (Inc 6).
CATEGORIES = ("lifecycle", "tool", "network", "consent", "result")


@dataclass
class RunEvent:
    """One line of a run's `events.jsonl`. ADR 0003 §11a.

    Always persisted; `level`/`category` are the two orthogonal filter axes
    a consumer uses to render more/less. `seq` is the monotonic per-run
    cursor used by `?since=`.
    """

    seq: int
    ts: float
    type: str
    level: str = "info"
    category: str = "lifecycle"
    data: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "RunEvent":
        known = {f for f in cls.__dataclass_fields__}  # type: ignore[attr-defined]
        return cls(**{k: v for k, v in d.items() if k in known})

    def passes(self, min_level: str = "debug", categories: Optional[set[str]] = None) -> bool:
        """True if this event survives the given filters (used on read)."""
        if _LEVEL_RANK.get(self.level, 1) < _LEVEL_RANK.get(min_level, 0):
            return False
        if categories and self.category not in categories:
            return False
        return True


# ---------------------------------------------------------------------------
# Persistence contract (the seam — Item 35 plugs new backends in here)
# ---------------------------------------------------------------------------


class AgentRunStore(Protocol):
    """Storage contract for agent runs. Grows additively per increment.

    Inc 1: persist_meta / load_meta / list_meta.
    Inc 3: append_event / read_events.
    T5 (debt r): persist_state / load_state — the Triplet's third file.
    """

    def persist_meta(self, meta: RunMeta) -> None:
        """Write (create or overwrite) the run's meta record."""
        ...

    def load_meta(self, run_id: str, agent_n: int = 0) -> Optional[RunMeta]:
        """Load a run slot's meta, or None if unknown. `agent_n=0` is the
        top-level run; sub-agent slots (Inc 7) use higher indices."""
        ...

    def list_meta(self) -> list[RunMeta]:
        """All known runs' meta, newest-first by created_at."""
        ...

    def append_event(self, run_id: str, event: RunEvent, agent_n: int = 0) -> None:
        """Append one event to the run slot's events.jsonl (Inc 3)."""
        ...

    def read_events(self, run_id: str, agent_n: int = 0) -> list[RunEvent]:
        """Read all events for a run slot, in seq order (Inc 3).

        Filtering by level/category is applied by the caller via
        `RunEvent.passes` so the store stays a dumb sink.
        """
        ...

    def persist_state(self, run_id: str, state: dict, agent_n: int = 0) -> None:
        """Write (create or overwrite) the run slot's `state.json` (T5 —
        debt r). The run's own lifecycle checkpoint: what a restart or a
        later /resume (T7) needs to pick the run back up. Whole-document
        replace, atomic like persist_meta."""
        ...

    def load_state(self, run_id: str, agent_n: int = 0) -> Optional[dict]:
        """Load the run slot's `state.json`, or None if absent/corrupt (T5)."""
        ...


# ---------------------------------------------------------------------------
# Filesystem implementation (Inc 1 concrete store)
# ---------------------------------------------------------------------------


class FilesystemAgentRunStore:
    """`AgentRunStore` backed by `~/.ppxai/runs/<run_id>/agent-<n>/`.

    The directory IS the ADR 0005 Inspection Triplet path, and all three
    Triplet files now live here: `meta.json` (Inc 1), `events.jsonl`
    (Inc 3), and `state.json` (T5 — the run's lifecycle checkpoint, written
    when a run parks in `waiting`). Co-located readers may `cat` these
    directly; the registry API is the contract for remote/pod readers
    (ADR 0003 §6).
    """

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def _slot_dir(self, run_id: str, agent_n: int = 0) -> Path:
        return self._runs_dir / run_id / f"agent-{agent_n}"

    def _atomic_write_json(self, slot: Path, filename: str, payload: dict) -> None:
        """Atomic whole-document JSON write: unique tmp (mkstemp) + replace, so
        a crash mid-write can't leave a half-written file that breaks readers.
        A UNIQUE tmp name (not a fixed ".json.tmp") avoids two concurrent
        writers racing on the same temp path — harmless today (one event loop,
        no await between write and replace, per-run slot dir) but correct under
        a future multi-worker deployment (Gemini review #4, defense-in-depth)."""
        slot.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(
            dir=slot, prefix=f"{Path(filename).stem}-", suffix=".json.tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
            os.replace(tmp_path, slot / filename)
        except BaseException:
            # Don't leak the temp file if the write/replace fails.
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def persist_meta(self, meta: RunMeta) -> None:
        slot = self._slot_dir(meta.run_id, meta.agent_n)
        self._atomic_write_json(slot, "meta.json", meta.to_dict())

    def load_meta(self, run_id: str, agent_n: int = 0) -> Optional[RunMeta]:
        path = self._slot_dir(run_id, agent_n) / "meta.json"
        if not path.exists():
            return None
        try:
            return RunMeta.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError, TypeError) as exc:
            logger.warning(f"Corrupt run meta for {run_id}: {exc}")
            return None

    def list_meta(self) -> list[RunMeta]:
        if not self._runs_dir.exists():
            return []
        metas: list[RunMeta] = []
        for run_dir in self._runs_dir.iterdir():
            if not run_dir.is_dir():
                continue
            # Inc 1: only the top-level agent-0 slot. Sub-agent slots
            # (agent-1+) are listed once Inc 7 introduces them.
            meta = self.load_meta(run_dir.name, agent_n=0)
            if meta is not None:
                metas.append(meta)
        metas.sort(key=lambda m: m.created_at, reverse=True)
        return metas

    def append_event(self, run_id: str, event: RunEvent, agent_n: int = 0) -> None:
        slot = self._slot_dir(run_id, agent_n)
        slot.mkdir(parents=True, exist_ok=True)
        # Append-only: one JSON object per line. Open in append mode so
        # concurrent appends within a process serialize cleanly.
        with (slot / "events.jsonl").open("a", encoding="utf-8") as f:
            f.write(json.dumps(event.to_dict()) + "\n")

    def read_events(self, run_id: str, agent_n: int = 0) -> list[RunEvent]:
        path = self._slot_dir(run_id, agent_n) / "events.jsonl"
        if not path.exists():
            return []
        events: list[RunEvent] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(RunEvent.from_dict(json.loads(line)))
            except (json.JSONDecodeError, TypeError):
                # A torn last line (crash mid-append) is skipped, not fatal.
                continue
        return events

    def persist_state(self, run_id: str, state: dict, agent_n: int = 0) -> None:
        slot = self._slot_dir(run_id, agent_n)
        self._atomic_write_json(slot, "state.json", state)

    def load_state(self, run_id: str, agent_n: int = 0) -> Optional[dict]:
        path = self._slot_dir(run_id, agent_n) / "state.json"
        if not path.exists():
            return None
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            return loaded if isinstance(loaded, dict) else None
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning(f"Corrupt run state for {run_id}: {exc}")
            return None


# ---------------------------------------------------------------------------
# Run control — cooperative cancel + budget caps (Inc 6)
# ---------------------------------------------------------------------------


class RunStopped(Exception):
    """Base for a non-error, non-completion stop of a run (Inc 6).

    Unlike a failure, these are *expected* terminal/non-terminal stops the
    runner raises (or `check_control` raises into it) so `run_in_background`
    records the right status instead of `failed`. `resumable` marks whether a
    future resume could meaningfully pick up (conditional-resume, ADR #5).
    """

    status = "failed"      # subclasses override
    resumable = False

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


class RunCancelled(RunStopped):
    """The owner asked to cancel via POST .../cancel. Terminal, resumable —
    the run stopped cooperatively at a checkpoint, not mid-tool-call."""

    status = "cancelled"
    resumable = True


class RunBudgetExceeded(RunStopped):
    """A budget cap (iterations/time/tokens) was hit. Terminal, resumable —
    the work so far is intact; a resume with a larger budget could continue."""

    status = "interrupted"
    resumable = True


@dataclass
class RunControl:
    """Per-run cooperative control the runner polls between iterations.

    The registry owns one of these per in-flight run. `cancel_run` flips
    `cancel_requested`; the runner calls `check()` at each loop boundary,
    which raises `RunCancelled` / `RunBudgetExceeded` when it should stop.
    Cooperative (not task.cancel()) so a stop lands at a clean checkpoint —
    never mid-tool-call, which could leave a half-written artifact."""

    run_id: str
    budget: dict = field(default_factory=dict)
    started_at: float = 0.0
    cancel_requested: bool = False
    iterations: int = 0
    tokens_used: int = 0

    def check(self, *, now: float) -> None:
        """Raise if the run should stop. Called at each iteration boundary."""
        if self.cancel_requested:
            raise RunCancelled("cancelled by owner")
        max_iter = self.budget.get("iterations")
        if max_iter is not None and self.iterations >= max_iter:
            raise RunBudgetExceeded(f"iteration budget {max_iter} reached")
        max_time = self.budget.get("time_s")
        if max_time is not None and self.started_at and (now - self.started_at) >= max_time:
            raise RunBudgetExceeded(f"time budget {max_time}s reached")
        max_tok = self.budget.get("tokens")
        if max_tok is not None and self.tokens_used >= max_tok:
            raise RunBudgetExceeded(f"token budget {max_tok} reached")


# ---------------------------------------------------------------------------
# Registry service (the behavior over the store)
# ---------------------------------------------------------------------------


class AgentRunRegistry:
    """Mints run identities and answers lifecycle/query calls.

    Depends on the `AgentRunStore` Protocol, not on the filesystem
    directly, so swapping in a SQLite/other backend (Item 35) needs no
    change here. Inc 1 verbs: `start_run`, `get_run`, `list_runs`. Later
    increments add `events`, `cancel`, sub-agent spawn, etc.
    """

    def __init__(self, store: AgentRunStore) -> None:
        self._store = store
        # In-flight background tasks. We hold strong refs so the event loop
        # doesn't GC a running task mid-flight (asyncio only keeps weak refs).
        # Inc 2: fire-and-track. Cancel-by-id + shutdown drain land in Inc 6.
        self._tasks: set[asyncio.Task] = set()
        # Inc 6: per-run task + cooperative control, keyed by run_id, so
        # cancel-by-id can find the in-flight run and flip its control flag.
        # Entries are removed when the run finishes.
        self._run_tasks: dict[str, asyncio.Task] = {}
        self._controls: dict[str, RunControl] = {}
        # T5: per-run pending consent park, keyed by run_id. Each entry is
        # {"future": asyncio.Future, "token": str, "expires_at": float}. The
        # runner awaits the future inside park_run; respond_run (POST
        # .../respond) resolves it. In-memory only — a parked run does NOT
        # survive a restart in flight (its state.json checkpoint does; T7
        # resume is the consumer).
        self._waiters: dict[str, dict[str, Any]] = {}
        # Inc 3: per-run monotonic event seq + live subscribers (asyncio
        # Queues) for the SSE tail. Persisted events are the source of truth;
        # subscribers are a fan-out for live delivery only.
        self._seq: dict[str, int] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}
        # Inc 9: lightweight on-change hooks. The server registers one to push
        # an updated `background_agents` summary into AppState (state_sync) when
        # a run starts or reaches a terminal state. Kept generic (not coupled to
        # AppState) so the registry stays UI-agnostic.
        self._change_listeners: list = []
        # In-memory index of NON-terminal runs → their badge summary, keyed by
        # run_id and ordered newest-first by insertion. Maintained at each state
        # transition (pending / running / cancelling / terminal) so
        # active_summary() is O(active) with ZERO disk reads. Previously it
        # scanned list_runs() (read+parse meta.json for EVERY historical run)
        # on every lifecycle event — an O(N) disk bottleneck on the event loop
        # that grew with total run count (Gemini review #2, 2026-06-17).
        self._active: dict[str, dict[str, Any]] = {}

    # -- Inc 9: active-run summary + change notification ------------------
    _TERMINAL_STATUSES = frozenset(
        {"completed", "failed", "cancelled", "interrupted"}
    )

    def on_change(self, callback) -> None:
        """Register a no-arg callback fired when the active-run set may have
        changed (run start / terminal transition). Exceptions are swallowed so
        one bad listener can't wedge run execution."""
        self._change_listeners.append(callback)

    def _notify_change(self) -> None:
        for cb in list(self._change_listeners):
            try:
                cb()
            except Exception:
                logger.error("agent-run change listener raised", exc_info=True)

    def _index_active(self, meta: "RunMeta") -> None:
        """Upsert a run into the in-memory active index (or remove it once
        terminal). Called at every state transition so `active_summary()` never
        touches disk. Newest-first order: a re-inserted run keeps its original
        position (dict preserves insertion order; we pop-then-set only on the
        very first insert)."""
        if meta.status in self._TERMINAL_STATUSES:
            self._active.pop(meta.run_id, None)
            return
        # Update in place if already present (status change), else append.
        # parent_run_id is carried so the cancel cascade can find in-flight
        # children from memory (no per-child disk read — Gemini review #3); it
        # is NOT exposed by active_summary() (badge fields only).
        self._active[meta.run_id] = {
            "run_id": meta.run_id,
            "status": meta.status,
            "task": meta.task,
            "owner": meta.owner,
            "parent_run_id": meta.parent_run_id,
        }

    def active_summary(self) -> list[dict[str, Any]]:
        """Compact summary of NON-terminal runs, newest first, for the
        AppState `background_agents` mirror. Only fields a badge needs —
        never the result body or events.

        O(active), no disk I/O: reads the in-memory `_active` index maintained
        at each state transition (was an O(N) `list_runs()` disk scan per
        lifecycle event — Gemini review #2). `_active` is keyed newest-last by
        insertion; reverse for newest-first to match the prior contract.

        Projects to the badge fields only — `parent_run_id` is kept in the index
        (for the cancel cascade) but NOT surfaced here."""
        return [
            {"run_id": e["run_id"], "status": e["status"],
             "task": e["task"], "owner": e["owner"]}
            for e in reversed(list(self._active.values()))
        ]

    @staticmethod
    def _new_run_id() -> str:
        # Short, URL-safe, collision-resistant. Not time-ordered on purpose
        # (created_at carries ordering); keeps ids opaque.
        return f"run_{secrets.token_hex(6)}"

    def start_run(
        self,
        task: str,
        *,
        tools: Optional[list[str]] = None,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        parent_run_id: Optional[str] = None,
        network: Optional[list] = None,
        budget: Optional[dict] = None,
        owner: Optional[str] = None,
    ) -> RunMeta:
        """Mint a run, persist it in `pending` state, return its meta.

        Named per the ADR 0003 contract verb (`start_run`). In Inc 1
        execution is still the caller's responsibility (the route runs the
        task synchronously then calls `finish_run`); Inc 2 moves execution
        into a background task driven by the registry, at which point this
        method genuinely *starts* the run end-to-end.
        """
        meta = RunMeta(
            run_id=self._new_run_id(),
            task=task,
            status="pending",
            tools=list(tools or []),
            network=list(network or []),
            budget=dict(budget or {}),
            provider=provider,
            model=model,
            parent_run_id=parent_run_id,
            owner=owner,
            created_at=time.time(),
        )
        self._store.persist_meta(meta)
        self._index_active(meta)  # pending → enters the active index
        logger.info(f"Agent run created: {meta.run_id} (task={task[:40]!r})")
        return meta

    def finish_run(
        self,
        meta: RunMeta,
        *,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
        resumable: bool = False,
    ) -> RunMeta:
        """Mark a run terminal (completed/failed/cancelled/interrupted) and persist."""
        meta.status = status
        meta.result = result
        meta.error = error
        meta.resumable = resumable
        meta.finished_at = time.time()
        self._store.persist_meta(meta)
        self._index_active(meta)  # terminal → removed from the active index
        logger.info(f"Agent run {meta.run_id} -> {status}")
        self._notify_change()  # Inc 9: run left the active set
        return meta

    def get_control(self, run_id: str) -> "Optional[RunControl]":
        """The in-flight run's cooperative control, or None if not running.
        The runner uses this to poll budget/cancel at each iteration boundary."""
        return self._controls.get(run_id)

    def get_run_task(self, run_id: str) -> "Optional[asyncio.Task]":
        """The in-flight run's background asyncio.Task, or None if not running.
        Lets a waiter (e.g. spawn_subagent's parent) await the child's
        completion directly instead of polling get_run() off disk."""
        return self._run_tasks.get(run_id)

    def cancel_run(self, run_id: str) -> bool:
        """Request cooperative cancellation of an in-flight run (Inc 6).

        Flips the run's control flag and moves it to `cancelling`; the runner
        observes it at the next `check()` and raises `RunCancelled`, so the
        stop lands at a clean checkpoint (never mid-tool-call). Returns False
        if the run isn't in flight (already terminal / unknown).

        CASCADE (Item 37e/secondary review): also cancels any in-flight runs
        whose `parent_run_id == run_id`, so cancelling a parent never orphans
        a sub-agent that keeps consuming budget/LLM calls. This is the
        *correctness* guarantee — independent of whether the parent happens to
        be polling in `SpawnSubagentTool._await_child` (that poll is the
        latency optimization). The cascade walks the active-control set, so it
        is recursion-safe for future N>1 / deeper trees, and a cycle can't
        loop forever (a run already in `cancelling`/terminal is skipped)."""
        return self._cancel_run_cascade(run_id, _seen=set())

    def _cancel_run_cascade(self, run_id: str, *, _seen: set) -> bool:
        if run_id in _seen:
            return False  # cycle guard (shouldn't happen with parent_run_id DAG)
        _seen.add(run_id)

        control = self._controls.get(run_id)
        cancelled_self = False
        if control is not None:
            control.cancel_requested = True
            # T5: a PARKED run is blocked awaiting its consent future, not
            # polling check() — resolve the waiter with a denial so the runner
            # unblocks promptly (and then observes cancel_requested at its next
            # checkpoint) instead of idling out the full consent TTL.
            waiter = self._waiters.get(run_id)
            if waiter is not None and not waiter["future"].done():
                waiter["future"].set_result(
                    {"approved": False, "text": None, "via": "cancelled"}
                )
            meta = self._store.load_meta(run_id)
            if meta is not None and meta.status == "running":
                meta.status = "cancelling"
                self._store.persist_meta(meta)
                self._index_active(meta)  # running → cancelling (still active)
                self.emit_event(
                    run_id, "agent_run_cancelling", level="warning",
                    category="lifecycle",
                    data={"reason": "cancel requested by owner"},
                )
                self._notify_change()  # Inc 9: status changed (running->cancelling)
            cancelled_self = True

        # Cascade to in-flight children. A child is in-flight iff it has a live
        # control; its parent_run_id is read from the in-memory _active index
        # (Gemini review #3) — no per-child meta.json disk read, so a cascade
        # over C in-flight runs at depth D costs zero I/O instead of O(C*D).
        for child_id in list(self._controls.keys()):
            if child_id == run_id:
                continue
            child = self._active.get(child_id)
            if child is not None and child.get("parent_run_id") == run_id:
                self._cancel_run_cascade(child_id, _seen=_seen)

        return cancelled_self

    # --- interactive consent park/resume (T5) -----------------------------

    async def park_run(
        self,
        meta: RunMeta,
        *,
        kind: str,
        prompt: str,
        ttl_s: float,
        data: Optional[dict] = None,
    ) -> dict:
        """Park an in-flight run in `waiting{kind}` until POST .../respond
        answers it (or the TTL expires) — ADR 0003 §8 / build plan T5.

        Called from INSIDE the run's own coroutine (e.g. the spawn-consent
        adapter in build_task_runner), so "the run parks" literally means this
        await blocks the runner at a clean checkpoint. What happens:

          1. status -> "waiting"; `meta.waiting` carries {kind, prompt, token,
             since, expires_at, ttl_s} (the pane's consent card reads it).
          2. state.json checkpoint is written (debt r — a parked run must
             survive a restart INSPECTABLY; the in-flight future does not).
          3. `agent_waiting` event (category=consent) fans out to the run's
             live SSE tail — the token rides along so a watching client can
             respond without an extra meta fetch.
          4. Awaits the respond future, bounded by ttl_s. Timeout resolves to
             a DENIAL (fail-closed), never an approval.
          5. status -> "running"; waiting cleared; `agent_resumed` event with
             the outcome; state.json updated.

        Returns the response dict {"approved": bool|None, "text": str|None,
        "via": "respond"|"timeout"|"cancelled"}. `kind` is the waiting flavor
        ("consent" now; "input" when an ask-user tool lands).
        """
        run_id = meta.run_id
        if run_id in self._waiters:
            raise RuntimeError(f"run {run_id} is already parked")
        control = self._controls.get(run_id)
        if control is not None and control.cancel_requested:
            # A cancel is already pending — don't park at all (the waiter
            # would never be resolved by that earlier cancel).
            return {"approved": False, "text": None, "via": "cancelled"}

        token = secrets.token_hex(8)
        now = time.time()
        waiting = {
            "kind": kind,
            "prompt": prompt,
            "token": token,
            "since": now,
            "expires_at": now + ttl_s,
            "ttl_s": ttl_s,
        }
        meta.status = "waiting"
        meta.waiting = waiting
        self._store.persist_meta(meta)
        self._index_active(meta)  # running -> waiting (still active)
        self._store.persist_state(run_id, {
            "schema": 1,
            "run_id": run_id,
            "status": "waiting",
            "waiting": dict(waiting),
            "updated_at": now,
        }, agent_n=meta.agent_n)
        self.emit_event(
            run_id, "agent_waiting", level="info", category="consent",
            data={**(data or {}), **waiting},
        )
        self._notify_change()  # status changed (running -> waiting)

        future: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters[run_id] = {
            "future": future, "token": token, "expires_at": waiting["expires_at"],
        }
        try:
            response = await asyncio.wait_for(future, timeout=ttl_s)
        except asyncio.TimeoutError:
            # Fail-closed: an unanswered park is a denial, not an approval.
            response = {"approved": False, "text": None, "via": "timeout"}
        finally:
            self._waiters.pop(run_id, None)

        resolved_at = time.time()
        meta.status = "running"
        meta.waiting = None
        self._store.persist_meta(meta)
        self._index_active(meta)  # waiting -> running
        self._store.persist_state(run_id, {
            "schema": 1,
            "run_id": run_id,
            "status": "running",
            "waiting": None,
            "last_response": {
                "kind": kind,
                "approved": response.get("approved"),
                "via": response.get("via"),
                "at": resolved_at,
            },
            "updated_at": resolved_at,
        }, agent_n=meta.agent_n)
        self.emit_event(
            run_id, "agent_resumed", level="info", category="consent",
            data={
                "kind": kind,
                "approved": bool(response.get("approved")),
                "via": response.get("via"),
            },
        )
        self._notify_change()  # status changed (waiting -> running)
        return response

    def respond_run(
        self,
        run_id: str,
        *,
        token: str,
        approved: Optional[bool] = None,
        text: Optional[str] = None,
    ) -> tuple[bool, str]:
        """Deliver a human response to a parked run (T5). Returns
        (ok, reason): ok=True resolved the park; otherwise `reason` says why
        not — the route maps it onto a 409.

        Token-checked: the caller must present the resume token minted at
        park time (from the run meta's `waiting.token` or the `agent_waiting`
        event), so a respond can never land on the WRONG park — a stale
        client answering after a timeout-deny + re-park would otherwise
        approve a question it never saw."""
        waiter = self._waiters.get(run_id)
        if waiter is None:
            return (
                False,
                "run is not awaiting a response (not parked, already "
                "answered, or the server restarted since it parked)",
            )
        if token != waiter["token"]:
            return (False, "resume token mismatch")
        if waiter["future"].done():
            return (False, "already answered")
        waiter["future"].set_result(
            {"approved": approved, "text": text, "via": "respond"}
        )
        return (True, "")

    def run_in_background(
        self,
        meta: RunMeta,
        runner: "Callable[[RunMeta], Awaitable[str]]",
    ) -> None:
        """Drive a run to completion in a background asyncio task (Inc 2).

        Flips the run to `running` and persists it, then schedules
        `runner(meta)` — an async callable that performs the actual work
        (the route supplies one that calls `provider.oneshot`) and returns
        the result body. On success the run is finished `completed` with
        that body; on any exception it's finished `failed` with the error.

        Fire-and-track: the task is held in `self._tasks` (and, keyed by id,
        in `self._run_tasks`) so it isn't GC'd, and removed on completion. The
        caller returns immediately — it does NOT await the task. Inc 6: a
        cooperative `RunControl` is registered so cancel-by-id / budget caps
        can stop the run at a clean checkpoint; `RunStopped` subclasses map to
        cancelled/interrupted statuses instead of `failed`.
        """
        meta.status = "running"
        meta.started_at = time.time()
        self._store.persist_meta(meta)
        self._index_active(meta)  # pending → running (in-place status update)
        # Inc 6: register the cooperative control so cancel/budget can reach
        # this run. The runner polls registry.get_control(run_id).check(...).
        # started_at here is MONOTONIC (for the time_s budget) — distinct from
        # meta.started_at (wall-clock, for display); check() is passed
        # time.monotonic() to match.
        control = RunControl(
            run_id=meta.run_id, budget=dict(meta.budget or {}),
            started_at=time.monotonic(),
        )
        self._controls[meta.run_id] = control
        self.emit_event(
            meta.run_id, "agent_run_start", level="info", category="lifecycle",
            data={"task": meta.task, "provider": meta.provider, "model": meta.model},
        )
        self._notify_change()  # Inc 9: run entered the active set

        async def _drive() -> None:
            try:
                body = await runner(meta)
                self.finish_run(meta, status="completed", result=body)
                self.emit_event(
                    meta.run_id, "agent_run_complete", level="info",
                    category="result", data={"chars": len(body or "")},
                )
            except RunStopped as stop:
                # Expected non-failure stop (cancel / budget). Record the
                # subclass's status + resumable flag, not `failed`.
                logger.info(f"Agent run {meta.run_id} stopped: {stop.status} ({stop.reason})")
                self.finish_run(
                    meta, status=stop.status, error=stop.reason,
                    resumable=stop.resumable,
                )
                self.emit_event(
                    meta.run_id, f"agent_run_{stop.status}", level="warning",
                    category="lifecycle",
                    data={"reason": stop.reason, "resumable": stop.resumable},
                )
            except Exception as exc:  # noqa: BLE001 — record any failure
                logger.warning(f"Agent run {meta.run_id} failed: {exc}")
                self.finish_run(meta, status="failed", error=str(exc))
                self.emit_event(
                    meta.run_id, "agent_run_error", level="error",
                    category="lifecycle", data={"error": str(exc)},
                )
            finally:
                self._controls.pop(meta.run_id, None)
                self._run_tasks.pop(meta.run_id, None)

        task = asyncio.create_task(_drive())
        self._tasks.add(task)
        self._run_tasks[meta.run_id] = task
        task.add_done_callback(self._tasks.discard)

    # --- events (Inc 3) -------------------------------------------------

    def emit_event(
        self,
        run_id: str,
        type_: str,
        *,
        level: str = "info",
        category: str = "lifecycle",
        data: Optional[dict] = None,
        agent_n: int = 0,
    ) -> RunEvent:
        """Assign a per-run seq, persist to events.jsonl, fan out to live
        SSE subscribers. Persisted record is the source of truth; the
        fan-out is best-effort live delivery."""
        # Seed seq from persisted max on first emit for this run (so a fresh
        # registry process doesn't restart seq at 1 and collide with existing
        # events — matters once runs outlive a restart, Inc 6).
        if run_id not in self._seq:
            existing = self._store.read_events(run_id, agent_n=agent_n)
            self._seq[run_id] = max((e.seq for e in existing), default=0)
        seq = self._seq[run_id] + 1
        self._seq[run_id] = seq
        event = RunEvent(
            seq=seq, ts=time.time(), type=type_,
            level=level, category=category, data=data or {},
        )
        self._store.append_event(run_id, event, agent_n=agent_n)
        for q in list(self._subscribers.get(run_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer: never block the emitter, never silently lose
                # the event (it's already on disk — events.jsonl is the source
                # of truth). Flag the queue overflowed; the SSE generator
                # self-heals by replaying missed events from disk via
                # read_events(since=last_seq), then resumes the live tail.
                q._ppxai_overflowed = True  # type: ignore[attr-defined]
        return event

    def read_events(
        self,
        run_id: str,
        *,
        since: int = 0,
        min_level: str = "debug",
        categories: Optional[set[str]] = None,
        agent_n: int = 0,
    ) -> list[RunEvent]:
        """Replay persisted events after `since`, applying level/category
        filters (ADR 0003 §11a)."""
        out = []
        for ev in self._store.read_events(run_id, agent_n=agent_n):
            if ev.seq <= since:
                continue
            if ev.passes(min_level=min_level, categories=categories):
                out.append(ev)
        return out

    def subscribe(self, run_id: str) -> asyncio.Queue:
        """Register a live subscriber queue for a run's SSE tail.

        The queue carries a `_ppxai_overflowed` flag (set by emit_event on
        QueueFull) so the consumer can detect it fell behind and self-heal
        from disk rather than silently miss events.
        """
        q: asyncio.Queue = asyncio.Queue(maxsize=1000)
        q._ppxai_overflowed = False  # type: ignore[attr-defined]
        self._subscribers.setdefault(run_id, set()).add(q)
        return q

    def unsubscribe(self, run_id: str, q: asyncio.Queue) -> None:
        subs = self._subscribers.get(run_id)
        if subs:
            subs.discard(q)
            if not subs:
                self._subscribers.pop(run_id, None)

    def get_run(self, run_id: str) -> Optional[RunMeta]:
        return self._store.load_meta(run_id)

    def list_runs(self) -> list[RunMeta]:
        return self._store.list_meta()
