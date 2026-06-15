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
    status: str = "pending"  # pending | running | completed | failed (grows in Inc 2/6)
    agent_n: int = 0  # slot index; 0 = top-level run, >0 = sub-agents (Inc 7)
    parent_run_id: Optional[str] = None  # set for sub-agents (Inc 7)
    provider: Optional[str] = None
    model: Optional[str] = None
    tools: list[str] = field(default_factory=list)  # the grant (enforced in Inc 4)
    network: list = field(default_factory=list)  # egress allow_outbound (enforced in Inc 5); provenance/audit on disk
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
    Later: load_state / save_state, etc.
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


# ---------------------------------------------------------------------------
# Filesystem implementation (Inc 1 concrete store)
# ---------------------------------------------------------------------------


class FilesystemAgentRunStore:
    """`AgentRunStore` backed by `~/.ppxai/runs/<run_id>/agent-<n>/`.

    The directory IS the ADR 0005 Inspection Triplet path; `meta.json` is
    the first of the Triplet files (state.json / events.jsonl arrive in
    Inc 2-3). Co-located readers may `cat` these directly; the registry
    API is the contract for remote/pod readers (ADR 0003 §6).
    """

    def __init__(self, runs_dir: Path) -> None:
        self._runs_dir = runs_dir

    def _slot_dir(self, run_id: str, agent_n: int = 0) -> Path:
        return self._runs_dir / run_id / f"agent-{agent_n}"

    def persist_meta(self, meta: RunMeta) -> None:
        slot = self._slot_dir(meta.run_id, meta.agent_n)
        slot.mkdir(parents=True, exist_ok=True)
        path = slot / "meta.json"
        # Atomic-ish write: tmp + replace, so a crash mid-write can't leave
        # a half-written meta.json that breaks list_meta().
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(meta.to_dict(), indent=2), encoding="utf-8")
        os.replace(tmp, path)

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
        # Inc 3: per-run monotonic event seq + live subscribers (asyncio
        # Queues) for the SSE tail. Persisted events are the source of truth;
        # subscribers are a fan-out for live delivery only.
        self._seq: dict[str, int] = {}
        self._subscribers: dict[str, set[asyncio.Queue]] = {}

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
            provider=provider,
            model=model,
            parent_run_id=parent_run_id,
            created_at=time.time(),
        )
        self._store.persist_meta(meta)
        logger.info(f"Agent run created: {meta.run_id} (task={task[:40]!r})")
        return meta

    def finish_run(
        self,
        meta: RunMeta,
        *,
        status: str,
        result: Optional[str] = None,
        error: Optional[str] = None,
    ) -> RunMeta:
        """Mark a run terminal (completed/failed) and persist."""
        meta.status = status
        meta.result = result
        meta.error = error
        meta.finished_at = time.time()
        self._store.persist_meta(meta)
        logger.info(f"Agent run {meta.run_id} -> {status}")
        return meta

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

        Fire-and-track: the task is held in `self._tasks` so it isn't GC'd,
        and removed on completion. The caller (route) returns immediately
        after this returns — it does NOT await the task. Cancel-by-id and
        graceful-shutdown drain are Inc 6.
        """
        meta.status = "running"
        meta.started_at = time.time()
        self._store.persist_meta(meta)
        self.emit_event(
            meta.run_id, "agent_run_start", level="info", category="lifecycle",
            data={"task": meta.task, "provider": meta.provider, "model": meta.model},
        )

        async def _drive() -> None:
            try:
                body = await runner(meta)
                self.finish_run(meta, status="completed", result=body)
                self.emit_event(
                    meta.run_id, "agent_run_complete", level="info",
                    category="result", data={"chars": len(body or "")},
                )
            except Exception as exc:  # noqa: BLE001 — record any failure
                logger.warning(f"Agent run {meta.run_id} failed: {exc}")
                self.finish_run(meta, status="failed", error=str(exc))
                self.emit_event(
                    meta.run_id, "agent_run_error", level="error",
                    category="lifecycle", data={"error": str(exc)},
                )

        task = asyncio.create_task(_drive())
        self._tasks.add(task)
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
