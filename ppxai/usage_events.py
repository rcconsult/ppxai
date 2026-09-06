"""Cross-tier usage sink — ADR 0008 Option A, debt Item 49.

ppxai spends provider tokens through tiers that can run **concurrently for
one user against one provider account**: the interactive session, and the
background tiers (`/v1/oneshot` and `/v1/agent/task`, which since the FU
unification share one execution path through `build_task_runner`).

Each tier's client-side isolation was correct for its own purpose — oneshot
statelessness (ADR 0004), task blast-radius containment (ADR 0003 D1). But
`save_usage_to_persistent_storage`, the sole writer of `usage.json`, is
reachable only from interactive paths. The provider billed for all tiers;
`/cost` showed one. It under-reported silently, and silently is the problem:
a number users trust for budgeting was wrong in the direction of "cheaper
than reality" exactly when background runs were active.

**This module is the seam every token-spending path reports to.** It is an
append-only event log, not a mutable counter, and that choice is doing real
work:

- **Different providers price differently.** A single scalar total is
  meaningless when chat runs on Perplexity and a task runs on NVIDIA, so
  every event carries `(provider, model)` and totals are computed per key.
- **The writers are in different processes.** The interactive session lives
  in the TUI process; the background tiers live in the server, possibly
  across workers. A shared mutable counter is a lost-update race. Appends
  are not.
- **The questions are legitimately different.** "What did this tenant's
  task cost" and "what did I spend in chat" are both real. Tier- and
  owner-tagging answers both from one log; a merged scalar answers neither.

**Concurrency contract.** Each event is one line, written with a single
`os.write()` to a descriptor opened `O_APPEND`. The kernel makes the
offset-grab and the write atomic under `O_APPEND`, so concurrent writers
interleave whole lines rather than fragments — provided the line fits in one
write, which `_MAX_LINE` enforces. This is why the record is deliberately
flat and small: nesting invites growth, and growth past the limit would
silently start corrupting a file nobody reads until they need it.

**Reading is defensive by design.** A truncated final line (a process killed
mid-write) or a line from a future schema must not take down `/cost`, so
`read_usage_events` skips what it cannot parse rather than raising. The
count of skipped lines is returned so a caller can surface it instead of
pretending the total is complete.

**This sink never raises into a caller.** Accounting is telemetry: failing a
user's chat turn or a running agent because a log write failed would trade a
real operation for a bookkeeping one. Failures are logged at debug and
dropped, which means the log is best-effort and must not be presented as an
audit trail — see `docs/decisions/0008-cross-tier-cost-and-resource-accounting.md`.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from .common.logger import get_logger

logger = get_logger("usage")

#: Tier discriminators. `chat` is the interactive session; `oneshot` and
#: `task` are the two background run kinds, which map 1:1 onto `RunMeta.kind`.
TIER_CHAT = "chat"
TIER_ONESHOT = "oneshot"
TIER_TASK = "task"
TIERS = (TIER_CHAT, TIER_ONESHOT, TIER_TASK)

#: One event must fit in a single atomic append. 4096 is the POSIX PIPE_BUF
#: floor and a safe common denominator; a realistic event serializes to
#: ~200 bytes, so this is headroom rather than a constraint being tested.
_MAX_LINE = 4096

#: Line schema version, on EVERY event. Same discipline as ADR 0006's
#: `schema_version` on session JSON, and for a sharper reason here: this log
#: is best-effort and swallows its own failures, so a reader that met an
#: unversioned schema change would see it as a GAP rather than an error —
#: silently wrong totals instead of a loud break. With `v` present a reader
#: can refuse a line it does not understand and say so.
SCHEMA_VERSION = 1

#: Identity fields are truncated rather than dropped, so that no input can
#: push a line past `_MAX_LINE`. See `record_usage`: losing an event would
#: under-report, which is the exact defect this module exists to fix.
_MAX_IDENT = 200


@dataclass(frozen=True)
class UsageEvent:
    """One tier's token spend for one (provider, model), at one moment.

    Flat on purpose — see the module docstring on why the line has a size
    ceiling. `run_id` is None for interactive chat, which has no run.
    """

    ts: str
    provider: str
    model: str
    tier: str
    prompt_tokens: int
    completion_tokens: int
    estimated_cost: float
    owner: str | None = None
    run_id: str | None = None

    @property
    def total_tokens(self) -> int:
        return self.prompt_tokens + self.completion_tokens

    @property
    def key(self) -> str:
        """`provider/model`, matching `usage.json`'s existing rollup key."""
        return f"{self.provider}/{self.model}"


def events_file(usage_dir: Path | None = None) -> Path:
    """Path to the append log. Sibling of `usage.json`, same directory."""
    base = usage_dir if usage_dir is not None else Path.home() / ".ppxai" / "usage"
    return Path(base) / "usage-events.jsonl"


def record_usage(
    *,
    provider: str,
    model: str,
    tier: str,
    prompt_tokens: int,
    completion_tokens: int,
    estimated_cost: float,
    owner: str | None = None,
    run_id: str | None = None,
    usage_dir: Path | None = None,
) -> bool:
    """Append one usage event. Returns True when it was written.

    Never raises. A caller that wants to know whether accounting worked can
    read the return value; a caller in the middle of serving a user should
    ignore it and carry on.

    A zero-token event is dropped rather than written: the background tiers
    emit their terminal usage unconditionally, and a run that spent nothing
    would otherwise fill the log with rows that move no total.
    """
    if prompt_tokens <= 0 and completion_tokens <= 0 and estimated_cost <= 0:
        return False

    if tier not in TIERS:
        # Not fatal — an unknown tier still carries real money, and dropping
        # it would under-report in exactly the way this module exists to fix.
        logger.debug(f"usage event carries unknown tier {tier!r}; recording anyway")

    event = UsageEvent(
        ts=datetime.now().isoformat(),
        provider=provider or "unknown",
        model=model or "unknown",
        tier=tier,
        prompt_tokens=max(0, int(prompt_tokens)),
        completion_tokens=max(0, int(completion_tokens)),
        estimated_cost=float(estimated_cost or 0.0),
        owner=owner,
        run_id=run_id,
    )

    try:
        raw = _serialize(event)
        if len(raw) > _MAX_LINE:
            # Losing the whole event would under-report — the defect this
            # module exists to fix. So identity is shed, never money: the two
            # unbounded caller-supplied strings go first, then the remaining
            # identity fields are truncated to a bounded width. After that the
            # line length is bounded by construction, which is why there is no
            # "give up and drop it" branch: a silent drop in an append-only
            # log with no sequence number is invisible to every reader, and
            # "a partial total is never presented as a complete one" would
            # stop being true.
            event = UsageEvent(**{**asdict(event), "owner": None, "run_id": None})
            raw = _serialize(event)
            if len(raw) > _MAX_LINE:
                event = UsageEvent(**{
                    **asdict(event),
                    "provider": event.provider[:_MAX_IDENT],
                    "model": event.model[:_MAX_IDENT],
                    "tier": event.tier[:_MAX_IDENT],
                })
                raw = _serialize(event)

        path = events_file(usage_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.write(fd, raw)
        finally:
            os.close(fd)
        return True
    except Exception as e:  # noqa: BLE001 — accounting must never break a turn
        logger.debug(f"record_usage noop: {e}")
        return False


def _serialize(event: UsageEvent) -> bytes:
    """One event as one line, carrying the schema version."""
    payload = {"v": SCHEMA_VERSION, **asdict(event)}
    return (json.dumps(payload, ensure_ascii=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def read_usage_events(
    *,
    period: str = "all",
    tier: str | None = None,
    provider: str | None = None,
    usage_dir: Path | None = None,
) -> tuple[list[UsageEvent], int]:
    """Return `(events, skipped)` for the window, newest last.

    `skipped` counts lines that could not be parsed — a truncated tail from a
    killed process, or a row from a schema this build does not know. It is
    returned rather than logged away so a caller can tell the user the total
    is partial instead of quietly presenting it as complete.
    """
    path = events_file(usage_dir)
    if not path.exists():
        return [], 0

    cutoff = _period_cutoff(period)
    events: list[UsageEvent] = []
    skipped = 0

    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    raw = json.loads(line)
                    # An unversioned or future line is COUNTED as skipped, not
                    # coerced. Guessing at a schema we do not know would put a
                    # wrong number in front of someone budgeting with it.
                    if int(raw.get("v", 0)) != SCHEMA_VERSION:
                        skipped += 1
                        continue
                    event = UsageEvent(
                        ts=raw["ts"],
                        provider=raw["provider"],
                        model=raw["model"],
                        tier=raw["tier"],
                        prompt_tokens=int(raw["prompt_tokens"]),
                        completion_tokens=int(raw["completion_tokens"]),
                        estimated_cost=float(raw["estimated_cost"]),
                        owner=raw.get("owner"),
                        run_id=raw.get("run_id"),
                    )
                except (json.JSONDecodeError, KeyError, TypeError, ValueError):
                    skipped += 1
                    continue

                if tier is not None and event.tier != tier:
                    continue
                if provider is not None and event.provider != provider:
                    continue
                if cutoff is not None:
                    try:
                        if datetime.fromisoformat(event.ts) < cutoff:
                            continue
                    except ValueError:
                        skipped += 1
                        continue
                events.append(event)
    except OSError as e:
        logger.debug(f"read_usage_events noop: {e}")
        return [], skipped

    return events, skipped


def summarize_usage(
    *,
    period: str = "all",
    usage_dir: Path | None = None,
) -> dict[str, Any]:
    """Roll the log up into the shape `/cost` renders.

    `by_tier` is the answer Item 49 was filed for: it makes the background
    spend visible next to the interactive spend instead of absent from it.
    """
    events, skipped = read_usage_events(period=period, usage_dir=usage_dir)

    by_model: dict[str, dict[str, Any]] = {}
    by_tier: dict[str, dict[str, Any]] = {}
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "estimated_cost": 0.0}

    for e in events:
        for bucket, key in ((by_model, e.key), (by_tier, e.tier)):
            slot = bucket.setdefault(
                key,
                {"prompt_tokens": 0, "completion_tokens": 0,
                 "estimated_cost": 0.0, "events": 0},
            )
            slot["prompt_tokens"] += e.prompt_tokens
            slot["completion_tokens"] += e.completion_tokens
            slot["estimated_cost"] += e.estimated_cost
            slot["events"] += 1

        totals["prompt_tokens"] += e.prompt_tokens
        totals["completion_tokens"] += e.completion_tokens
        totals["estimated_cost"] += e.estimated_cost

    return {
        "period": period,
        "by_model": by_model,
        "by_tier": by_tier,
        "total_tokens": totals["prompt_tokens"] + totals["completion_tokens"],
        "prompt_tokens": totals["prompt_tokens"],
        "completion_tokens": totals["completion_tokens"],
        "total_cost": totals["estimated_cost"],
        "event_count": len(events),
        "skipped_lines": skipped,
    }


def _period_cutoff(period: str) -> datetime | None:
    """Window start for a period label, or None for 'all'."""
    windows = {
        "24h": timedelta(days=1),
        "week": timedelta(days=7),
        "month": timedelta(days=30),
        "year": timedelta(days=365),
    }
    delta = windows.get(period)
    return datetime.now() - delta if delta else None
