"""Cross-tier usage accounting — ADR 0008 Option A, debt Item 49.

The defect: `usage.json` is written only from interactive paths, so `/cost`
reported chat spend and silently omitted every `/v1/oneshot` and
`/v1/agent/task` token. The provider billed for all of them. Under-reporting
in the "cheaper than reality" direction is the dangerous one — the number is
trusted for budgeting.

These tests pin the sink's contract, the two taps that feed it, and the one
arithmetic trap in the rollup: chat spend is written to BOTH stores, so a
naive sum double-counts it.
"""

from __future__ import annotations

import json
import os
from concurrent.futures import ThreadPoolExecutor

import pytest

from ppxai.usage_events import (
    SCHEMA_VERSION,
    TIER_CHAT,
    TIER_ONESHOT,
    TIER_TASK,
    events_file,
    read_usage_events,
    record_usage,
    summarize_usage,
)


@pytest.fixture
def sink(tmp_path):
    """An isolated usage directory. Never the developer's real one."""
    return tmp_path / "usage"


class TestTheSinkRecords:
    def test_an_event_round_trips(self, sink):
        assert record_usage(
            provider="perplexity", model="sonar", tier=TIER_CHAT,
            prompt_tokens=100, completion_tokens=50, estimated_cost=0.001,
            usage_dir=sink,
        ) is True

        events, skipped = read_usage_events(usage_dir=sink)
        assert skipped == 0
        assert len(events) == 1
        assert events[0].key == "perplexity/sonar"
        assert events[0].total_tokens == 150

    def test_a_zero_spend_event_is_not_recorded(self, sink):
        """Background tiers emit terminal usage unconditionally; a run that
        spent nothing must not fill the log with rows that move no total."""
        assert record_usage(
            provider="p", model="m", tier=TIER_TASK,
            prompt_tokens=0, completion_tokens=0, estimated_cost=0.0,
            usage_dir=sink,
        ) is False
        assert not events_file(sink).exists()

    def test_recording_never_raises_into_the_caller(self, tmp_path):
        """Accounting is telemetry. Failing a user's turn over a log write
        would trade a real operation for a bookkeeping one."""
        wall = tmp_path / "wall"
        wall.write_text("not a directory", encoding="utf-8")

        assert record_usage(
            provider="p", model="m", tier=TIER_CHAT,
            prompt_tokens=1, completion_tokens=1, estimated_cost=0.1,
            usage_dir=wall,
        ) is False


class TestReadingIsDefensive:
    def test_a_corrupt_line_is_skipped_and_counted(self, sink):
        record_usage(provider="p", model="m", tier=TIER_CHAT,
                     prompt_tokens=10, completion_tokens=5,
                     estimated_cost=0.01, usage_dir=sink)
        with open(events_file(sink), "a", encoding="utf-8") as fh:
            fh.write("{ truncated mid-write\n")

        events, skipped = read_usage_events(usage_dir=sink)

        assert len(events) == 1, "a good row must survive a bad neighbour"
        assert skipped == 1, "the loss must be countable, not silent"

    def test_a_partial_total_is_never_presented_as_complete(self, sink):
        """`skipped_lines` is what lets /cost say the number is partial."""
        record_usage(provider="p", model="m", tier=TIER_CHAT,
                     prompt_tokens=10, completion_tokens=5,
                     estimated_cost=0.01, usage_dir=sink)
        with open(events_file(sink), "a", encoding="utf-8") as fh:
            fh.write("garbage\n")

        assert summarize_usage(usage_dir=sink)["skipped_lines"] == 1

    def test_a_missing_log_is_empty_not_an_error(self, sink):
        assert read_usage_events(usage_dir=sink) == ([], 0)
        assert summarize_usage(usage_dir=sink)["total_cost"] == 0.0


class TestConcurrentWritersDoNotCorruptTheLog:
    """The reason the record is flat and small.

    Each event is one `os.write()` to an O_APPEND descriptor, so the kernel
    makes offset-grab-and-write atomic and concurrent writers interleave
    whole lines. A mutable shared counter would lose updates here; that is
    the argument for an append log stated as a test.
    """

    def test_parallel_writes_all_survive_and_parse(self, sink):
        def write(n: int) -> None:
            record_usage(
                provider="p", model=f"m{n % 5}", tier=TIER_TASK,
                prompt_tokens=n + 1, completion_tokens=1,
                estimated_cost=0.001, run_id=f"run_{n}", usage_dir=sink,
            )

        with ThreadPoolExecutor(max_workers=16) as pool:
            list(pool.map(write, range(200)))

        events, skipped = read_usage_events(usage_dir=sink)
        assert skipped == 0, "interleaved writes produced an unparseable line"
        assert len(events) == 200
        assert sum(e.prompt_tokens for e in events) == sum(range(1, 201))

    def test_every_line_is_a_complete_json_object(self, sink):
        record_usage(provider="p", model="m", tier=TIER_ONESHOT,
                     prompt_tokens=1, completion_tokens=1,
                     estimated_cost=0.1, usage_dir=sink)
        for line in events_file(sink).read_text(encoding="utf-8").splitlines():
            json.loads(line)


class TestTheRollupAnswersItem49:
    def test_background_spend_is_visible_next_to_interactive(self, sink):
        record_usage(provider="perplexity", model="sonar", tier=TIER_CHAT,
                     prompt_tokens=100, completion_tokens=100,
                     estimated_cost=0.01, usage_dir=sink)
        record_usage(provider="nvidia", model="kimi", tier=TIER_TASK,
                     prompt_tokens=900, completion_tokens=100,
                     estimated_cost=0.20, run_id="r1", usage_dir=sink)
        record_usage(provider="perplexity", model="sonar", tier=TIER_ONESHOT,
                     prompt_tokens=50, completion_tokens=50,
                     estimated_cost=0.005, run_id="r2", usage_dir=sink)

        s = summarize_usage(usage_dir=sink)

        assert set(s["by_tier"]) == {TIER_CHAT, TIER_TASK, TIER_ONESHOT}
        assert s["by_tier"][TIER_TASK]["estimated_cost"] == pytest.approx(0.20)
        assert s["total_cost"] == pytest.approx(0.215)
        # The whole point: background is 95% of this bill and used to be zero.
        background = s["total_cost"] - s["by_tier"][TIER_CHAT]["estimated_cost"]
        assert background > s["by_tier"][TIER_CHAT]["estimated_cost"]

    def test_providers_are_kept_apart_because_pricing_differs(self, sink):
        """A single scalar lies when tiers sit on different providers."""
        record_usage(provider="perplexity", model="sonar", tier=TIER_CHAT,
                     prompt_tokens=1000, completion_tokens=0,
                     estimated_cost=0.001, usage_dir=sink)
        record_usage(provider="openai", model="gpt-5.6-terra", tier=TIER_TASK,
                     prompt_tokens=1000, completion_tokens=0,
                     estimated_cost=0.500, run_id="r", usage_dir=sink)

        by_model = summarize_usage(usage_dir=sink)["by_model"]

        assert by_model["perplexity/sonar"]["prompt_tokens"] == 1000
        assert by_model["openai/gpt-5.6-terra"]["prompt_tokens"] == 1000
        assert (by_model["openai/gpt-5.6-terra"]["estimated_cost"]
                > 100 * by_model["perplexity/sonar"]["estimated_cost"])

    def test_filters_narrow_to_one_tier(self, sink):
        record_usage(provider="p", model="m", tier=TIER_CHAT,
                     prompt_tokens=1, completion_tokens=1,
                     estimated_cost=0.1, usage_dir=sink)
        record_usage(provider="p", model="m", tier=TIER_TASK,
                     prompt_tokens=2, completion_tokens=2,
                     estimated_cost=0.2, run_id="r", usage_dir=sink)

        only_task, _ = read_usage_events(tier=TIER_TASK, usage_dir=sink)
        assert [e.tier for e in only_task] == [TIER_TASK]

    def test_owner_and_run_are_carried_for_per_tenant_attribution(self, sink):
        record_usage(provider="p", model="m", tier=TIER_TASK,
                     prompt_tokens=5, completion_tokens=5,
                     estimated_cost=0.5, owner="tenant-a", run_id="run_9",
                     usage_dir=sink)

        events, _ = read_usage_events(usage_dir=sink)
        assert events[0].owner == "tenant-a"
        assert events[0].run_id == "run_9"


class TestTheAtomicAppendCeiling:
    def test_an_oversized_event_sheds_identity_before_it_sheds_money(self, sink):
        """Losing the whole event would under-report — the defect itself."""
        huge = "x" * 5000

        assert record_usage(
            provider="p", model="m", tier=TIER_TASK,
            prompt_tokens=10, completion_tokens=10, estimated_cost=1.0,
            owner=huge, run_id=huge, usage_dir=sink,
        ) is True

        events, skipped = read_usage_events(usage_dir=sink)
        assert skipped == 0
        assert len(events) == 1
        assert events[0].estimated_cost == 1.0, "the money survived"
        assert events[0].owner is None, "the unbounded field was dropped"

    def test_no_input_can_cause_a_silent_drop(self, sink):
        """The ceiling must shed identity, never the event.

        A dropped line in an append-only log with no sequence number is
        invisible to every reader — the total would just be quietly low,
        which is the failure mode this module was built to end. Raised by
        the downstream consumer while the ADR was still uncommitted.
        """
        huge = "z" * 20_000

        assert record_usage(
            provider=huge, model=huge, tier=huge,
            prompt_tokens=7, completion_tokens=3, estimated_cost=2.5,
            owner=huge, run_id=huge, usage_dir=sink,
        ) is True

        events, skipped = read_usage_events(usage_dir=sink)
        assert skipped == 0
        assert len(events) == 1
        assert events[0].estimated_cost == 2.5
        assert events[0].total_tokens == 10

    def test_every_written_line_fits_the_atomic_ceiling(self, sink):
        record_usage(provider="p" * 100, model="m" * 100, tier=TIER_TASK,
                     prompt_tokens=1, completion_tokens=1,
                     estimated_cost=0.1, owner="o" * 100, run_id="r" * 100,
                     usage_dir=sink)

        for line in events_file(sink).read_bytes().splitlines(keepends=True):
            assert len(line) <= 4096


class TestTheLineSchemaIsVersioned:
    """A best-effort log that swallows failures needs a version MORE than a
    strict one does: a reader meeting an unversioned schema change sees a
    gap, not an error — silently wrong totals rather than a loud break.
    Same discipline as ADR 0006's `schema_version` on session JSON."""

    def test_every_line_carries_the_version(self, sink):
        record_usage(provider="p", model="m", tier=TIER_CHAT,
                     prompt_tokens=1, completion_tokens=1,
                     estimated_cost=0.1, usage_dir=sink)

        line = json.loads(events_file(sink).read_text(encoding="utf-8").strip())
        assert line["v"] == SCHEMA_VERSION

    def test_a_future_version_is_skipped_not_guessed_at(self, sink):
        """Coercing an unknown schema would put a wrong number in front of
        someone budgeting with it. Counted, so /cost can say it is partial."""
        record_usage(provider="p", model="m", tier=TIER_CHAT,
                     prompt_tokens=1, completion_tokens=1,
                     estimated_cost=0.1, usage_dir=sink)
        with open(events_file(sink), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "v": SCHEMA_VERSION + 1, "ts": "2099-01-01T00:00:00",
                "provider": "p", "model": "m", "tier": "chat",
                "prompt_tokens": 99, "completion_tokens": 99,
                "estimated_cost": 99.0,
            }) + "\n")

        events, skipped = read_usage_events(usage_dir=sink)

        assert len(events) == 1
        assert skipped == 1
        assert summarize_usage(usage_dir=sink)["total_cost"] == pytest.approx(0.1)

    def test_an_unversioned_line_is_not_silently_counted(self, sink):
        events_file(sink).parent.mkdir(parents=True, exist_ok=True)
        with open(events_file(sink), "w", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": "2026-01-01T00:00:00", "provider": "p", "model": "m",
                "tier": "chat", "prompt_tokens": 5, "completion_tokens": 5,
                "estimated_cost": 5.0,
            }) + "\n")

        events, skipped = read_usage_events(usage_dir=sink)
        assert events == []
        assert skipped == 1


class TestTheTapsAreWired:
    """A sink nothing calls is the same bug with more code."""

    def test_the_background_tap_exists_at_the_registry_boundary(self):
        """One tap covers BOTH background tiers: the FU unification made
        /v1/oneshot execute as a kind=oneshot registry run through the same
        builder, so tagging on `RunMeta.kind` separates them."""
        src = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            + "/ppxai/engine/task_runner.py"
        )
        with open(src, encoding="utf-8") as fh:
            text = fh.read()

        assert "record_usage(" in text
        assert 'getattr(m, "kind", None)' in text, (
            "the tier must come from RunMeta.kind, or oneshot and task spend "
            "land in the same bucket"
        )

    def test_the_interactive_tap_exists(self):
        src = (
            os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            + "/ppxai/engine/session.py"
        )
        with open(src, encoding="utf-8") as fh:
            text = fh.read()

        assert "record_usage(" in text
        assert "TIER_CHAT" in text
