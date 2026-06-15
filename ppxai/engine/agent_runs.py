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
# Persistence contract (the seam — Item 35 plugs new backends in here)
# ---------------------------------------------------------------------------


class AgentRunStore(Protocol):
    """Storage contract for agent runs. Inc 1 surface only.

    Later increments add methods to THIS protocol (append_event,
    load_state, save_state, …) — additive growth, never a reshape.
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

        async def _drive() -> None:
            try:
                body = await runner(meta)
                self.finish_run(meta, status="completed", result=body)
            except Exception as exc:  # noqa: BLE001 — record any failure
                logger.warning(f"Agent run {meta.run_id} failed: {exc}")
                self.finish_run(meta, status="failed", error=str(exc))

        task = asyncio.create_task(_drive())
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def get_run(self, run_id: str) -> Optional[RunMeta]:
        return self._store.load_meta(run_id)

    def list_runs(self) -> list[RunMeta]:
        return self._store.list_meta()
