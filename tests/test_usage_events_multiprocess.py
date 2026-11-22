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

import multiprocessing
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
