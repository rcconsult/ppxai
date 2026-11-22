"""Usage events from several processes at once all reach the log.

Windows emulates `O_APPEND` as seek-then-write, so two processes appending
at the same moment land on one offset and overwrite each other. Measured
2026-11-22 on Windows with only the in-process thread lock: 6 processes x
400 events, 2,112 of 2,401 lines survived and the reader reported 0
skipped, so every `/cost` total under-reported silently. `record_usage` now
takes an OS lock on Windows (`_ProcessLock`); POSIX appends were already
atomic, so on macOS and Linux this test passes on the old code too and the
Windows host is the one that proves the fix.
"""

from __future__ import annotations

import asyncio
import multiprocessing
import threading
import time
from pathlib import Path

from ppxai import usage_events
from ppxai.usage_events import TIER_TASK, read_usage_events, record_usage

PROCESSES = 6
EVENTS = 200


def _writer(usage_dir: str, start, worker: int) -> None:
    start.wait()
    for i in range(EVENTS):
        record_usage(provider="p", model=f"m{worker}", tier=TIER_TASK,
                     prompt_tokens=i, completion_tokens=1, estimated_cost=0.0,
                     usage_dir=Path(usage_dir))


def test_concurrent_processes_lose_no_event(tmp_path):
    ctx = multiprocessing.get_context("spawn")
    start = ctx.Event()
    procs = [ctx.Process(target=_writer, args=(str(tmp_path), start, w)) for w in range(PROCESSES)]
    for p in procs:
        p.start()
    start.set()
    for p in procs:
        p.join(120)
        assert p.exitcode == 0
    events, skipped = read_usage_events(usage_dir=tmp_path)
    assert skipped == 0
    assert len(events) == PROCESSES * EVENTS


def test_the_log_has_no_carriage_returns(tmp_path):
    record_usage(provider="p", model="m", tier=TIER_TASK, prompt_tokens=1,
                 completion_tokens=1, estimated_cost=0.0, usage_dir=tmp_path)
    assert b"\r" not in usage_events.events_file(tmp_path).read_bytes()


class _FakeMsvcrt:
    """`msvcrt.locking` that refuses `busy` times, then grants."""

    LK_NBLCK, LK_UNLCK, LK_LOCK = 2, 0, 1

    def __init__(self, busy: int):
        self.busy = busy
        self.calls: list[int] = []

    def locking(self, fd, mode, nbytes):
        self.calls.append(mode)
        if mode == self.LK_LOCK:
            raise AssertionError("LK_LOCK polls once a second and starves; use LK_NBLCK")
        if mode == self.LK_NBLCK and self.busy:
            self.busy -= 1
            raise OSError(36, "Resource deadlock avoided")


class TestTheWindowsLockRetries:
    """The retry loop, driven off-Windows with a stand-in `msvcrt`."""

    def test_a_busy_lock_is_retried_until_granted(self, tmp_path, monkeypatch):
        fake = _FakeMsvcrt(busy=5)
        monkeypatch.setattr(usage_events, "msvcrt", fake)
        with usage_events._ProcessLock(tmp_path / "usage-events.jsonl") as lock:
            assert lock._locked
        assert fake.calls == [fake.LK_NBLCK] * 6 + [fake.LK_UNLCK]

    def test_past_the_deadline_it_appends_unlocked(self, tmp_path, monkeypatch):
        fake = _FakeMsvcrt(busy=10**9)
        monkeypatch.setattr(usage_events, "msvcrt", fake)
        monkeypatch.setattr(usage_events, "_LOCK_DEADLINE_S", 0.05)
        assert record_usage(provider="p", model="m", tier=TIER_TASK, prompt_tokens=1,
                            completion_tokens=1, estimated_cost=0.0, usage_dir=tmp_path)
        assert fake.LK_UNLCK not in fake.calls
        assert len(read_usage_events(usage_dir=tmp_path)[0]) == 1


def _record(usage_dir: Path) -> bool:
    return record_usage(provider="p", model="m", tier=TIER_TASK, prompt_tokens=1,
                        completion_tokens=1, estimated_cost=0.0, usage_dir=usage_dir)


def _join_background_appends(timeout: float = 5.0) -> None:
    for t in threading.enumerate():
        if t.name == usage_events._BACKGROUND_THREAD_NAME:
            t.join(timeout)


def _lines(usage_dir: Path) -> int:
    return len(read_usage_events(usage_dir=usage_dir)[0])


class TestTheEventLoopNeverWaits:
    """Every chat turn records usage from the event loop (the server's SSE
    generators, both TUIs, /task's runner). A busy lock must not freeze it:
    on a loop, `record_usage` tries once and hands a busy append to a
    thread."""

    def test_a_free_lock_writes_at_once_on_the_loop(self, tmp_path):
        async def go():
            return _record(tmp_path)

        assert asyncio.run(go())
        assert _lines(tmp_path) == 1

    def test_a_stuck_windows_lock_does_not_block_the_loop(self, tmp_path, monkeypatch):
        fake = _FakeMsvcrt(busy=10**9)
        monkeypatch.setattr(usage_events, "msvcrt", fake)
        monkeypatch.setattr(usage_events, "_LOCK_DEADLINE_S", 1.0)

        async def go():
            start = time.monotonic()
            assert _record(tmp_path)
            return time.monotonic() - start

        assert asyncio.run(go()) < 0.5
        _join_background_appends()
        assert _lines(tmp_path) == 1  # written unlocked past the deadline, off the loop

    def test_a_busy_thread_lock_does_not_block_the_loop(self, tmp_path):
        async def go():
            start = time.monotonic()
            assert _record(tmp_path)
            return time.monotonic() - start

        with usage_events._WRITE_LOCK:
            assert asyncio.run(go()) < 0.5
            assert _lines(tmp_path) == 0
        _join_background_appends()
        assert _lines(tmp_path) == 1

    def test_off_the_loop_it_still_writes_before_returning(self, tmp_path, monkeypatch):
        fake = _FakeMsvcrt(busy=3)
        monkeypatch.setattr(usage_events, "msvcrt", fake)
        assert _record(tmp_path)
        assert _lines(tmp_path) == 1
