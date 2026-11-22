"""Cached input tokens are counted, priced, stored and shown everywhere usage is.

One meaning for every provider (see `UsageStats`): `prompt_tokens` is
UNCACHED input, `cache_read_input_tokens` / `cache_creation_input_tokens`
are the cached classes, `total_tokens` is all input plus output.

Before this, Anthropic's cache tokens were read by the provider and then
dropped at every site that summed or priced usage (live symptom: a /task
`run_usage` of prompt_tokens 6 against total_tokens 14,893, cost missing the
cache writes and a context badge near zero), and OpenAI / Gemini reported
cached input INSIDE `prompt_tokens`, which ppxai priced at the full rate.

The tests run the real engine paths (chat turn, tool loop, task runner,
oneshot recorder) over a scripted provider; only the wire is replaced.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import ppxai.config.providers as providers_cfg
from ppxai.commands import tools as tools_cmd
from ppxai.engine import task_runner
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore
from ppxai.engine.providers.gemini import GeminiProvider
from ppxai.engine.providers.usage_parse import (
    oneshot_usage_dict_from_sdk,
    oneshot_usage_dict_from_stats,
)
from ppxai.engine.providers.wire.responses import ResponsesHandler
from ppxai.engine.session import SessionManager
from ppxai.engine.types import Event, EventType, UsageStats
from ppxai.engine.usage_pricing import price_usage
from ppxai.server.routes import oneshot as oneshot_mod
from ppxai.usage import UsageStorage
from ppxai.usage_events import TIER_TASK, read_usage_events, record_usage, summarize_usage
from tests.fake_provider import FakeChatProvider
from tests.test_task_run_degradation_audit import ScriptedEngine, ScriptedProvider

MILLION = 1_000_000

#: $/MTok test pricing row, explicit on every class so the arithmetic is exact.
PRICING = {"input": 10.0, "output": 50.0, "cache_write": 12.5, "cache_read": 1.0}


def _cost(prompt, completion, cache_write, cache_read) -> float:
    return (
        prompt * PRICING["input"]
        + completion * PRICING["output"]
        + cache_write * PRICING["cache_write"]
        + cache_read * PRICING["cache_read"]
    ) / MILLION


@pytest.fixture
def priced():
    """Every provider/model priced with PRICING."""
    class _Rows(dict):
        def get(self, key, default=None):
            return PRICING

    with patch.object(providers_cfg, "get_model_pricing", lambda provider=None: _Rows()):
        yield


def _anthropic_usage(prompt=6, completion=100, write=10_000, read=4_000) -> UsageStats:
    """Shaped exactly like AnthropicProvider._usage's output."""
    return UsageStats(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=prompt + completion + write + read,
        cache_creation_input_tokens=write,
        cache_read_input_tokens=read,
    )


def _end(usage: UsageStats, text: str = "") -> Event:
    return Event(EventType.STREAM_END, text, {"usage": usage})


def _engine(iterations) -> ScriptedEngine:
    engine = ScriptedEngine(ScriptedProvider(iterations), budgets={})
    engine.set_provider("mock")
    engine.set_model("mock-model")
    return engine


async def _drain(engine, message="hi", stream=False):
    return [ev async for ev in engine.chat(message, stream=stream)]


# ---------------------------------------------------------------------------
# The engine paths: plain turn, tool loop
# ---------------------------------------------------------------------------


class TestPlainTurn:
    def test_cache_tokens_are_stored_and_priced(self, priced):
        engine = _engine([[_end(_anthropic_usage(), "pong")]])
        events = asyncio.run(_drain(engine))

        end = [e for e in events if e.type == EventType.STREAM_END][-1]
        u = end.metadata["usage"]
        assert u["cache_creation_input_tokens"] == 10_000
        assert u["cache_read_input_tokens"] == 4_000
        assert u["estimated_cost"] == pytest.approx(_cost(6, 100, 10_000, 4_000))

        session = engine.session.usage
        assert session.cache_creation_input_tokens == 10_000
        assert session.cache_read_input_tokens == 4_000
        assert session.estimated_cost == pytest.approx(_cost(6, 100, 10_000, 4_000))
        by_model = next(iter(engine.session.usage_by_model.values()))
        assert (by_model.cache_creation_input_tokens, by_model.cache_read_input_tokens) == (10_000, 4_000)

    def test_context_badge_counts_cached_input(self, priced):
        engine = _engine([[_end(_anthropic_usage(), "pong")]])
        asyncio.run(_drain(engine))
        # All input (6 + 10_000 + 4_000) + output (100), not prompt + completion = 106.
        assert engine._last_known_message_tokens == 6 + 10_000 + 4_000 + 100


class TestToolLoop:
    def _two_iteration_engine(self):
        call = Event(EventType.TOOL_CALL, {
            "tool": "ok_tool", "arguments": {"q": "x"}, "tool_call_id": "c1",
        })
        return _engine([
            [call, _end(_anthropic_usage(prompt=6, completion=40, write=9_000, read=0))],
            [_end(_anthropic_usage(prompt=3, completion=60, write=500, read=9_000), "Done.")],
        ])

    def test_every_iteration_is_summed_and_priced(self, priced):
        engine = self._two_iteration_engine()
        engine.enable_tools()
        events = asyncio.run(_drain(engine))

        end = [e for e in events if e.type == EventType.STREAM_END][-1]
        u = end.metadata["usage"]
        assert u["prompt_tokens"] == 9
        assert u["completion_tokens"] == 100
        assert u["cache_creation_input_tokens"] == 9_500
        assert u["cache_read_input_tokens"] == 9_000
        assert u["total_tokens"] == (6 + 40 + 9_000) + (3 + 60 + 500 + 9_000)
        assert u["estimated_cost"] == pytest.approx(_cost(9, 100, 9_500, 9_000))
        assert engine.session.usage.cache_read_input_tokens == 9_000

    def test_context_badge_uses_the_last_request_including_cache(self, priced):
        engine = self._two_iteration_engine()
        engine.enable_tools()
        asyncio.run(_drain(engine))
        assert engine._last_known_message_tokens == 3 + 500 + 9_000 + 60


# ---------------------------------------------------------------------------
# Task runner: run_usage event + the cross-tier sink
# ---------------------------------------------------------------------------


class TestTaskRunUsage:
    def test_run_usage_event_and_sink_carry_cache_tokens(self, tmp_path, monkeypatch, priced):
        call = Event(EventType.TOOL_CALL, {
            "tool": "ok_tool", "arguments": {"q": "x"}, "tool_call_id": "c1",
        })
        engine = ScriptedEngine(ScriptedProvider([
            [call, _end(_anthropic_usage(prompt=6, completion=40, write=9_000, read=0))],
            [_end(_anthropic_usage(prompt=3, completion=60, write=500, read=9_000), "Done.")],
        ]), budgets={})

        async def run():
            registry = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
            monkeypatch.setattr(task_runner, "EngineClient", lambda: engine)
            runner = task_runner.build_task_runner(
                registry, provider_name="mock", model="mock-model", task="do it",
                tools=["ok_tool"], allow_outbound=[],
            )
            meta = registry.start_run(
                "do it", tools=["ok_tool"], provider="mock", model="mock-model",
            )
            registry.run_in_background(meta, runner)
            await registry.get_run_task(meta.run_id)
            return meta.run_id

        run_id = asyncio.run(run())
        path = tmp_path / "runs" / run_id / "agent-0" / "events.jsonl"
        rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]
        [usage] = [r for r in rows if r["type"] == "run_usage"]
        data = usage["data"]
        assert data["prompt_tokens"] == 9
        assert data["cache_creation_input_tokens"] == 9_500
        assert data["cache_read_input_tokens"] == 9_000
        assert data["estimated_cost"] == pytest.approx(_cost(9, 100, 9_500, 9_000))

        events, skipped = read_usage_events(tier=TIER_TASK)
        assert skipped == 0
        [event] = [e for e in events if e.run_id == run_id]
        assert (event.cache_creation_input_tokens, event.cache_read_input_tokens) == (9_500, 9_000)
        assert event.estimated_cost == pytest.approx(_cost(9, 100, 9_500, 9_000))


# ---------------------------------------------------------------------------
# Oneshot: the recorder reads the provider's cache keys; the wire is unchanged
# ---------------------------------------------------------------------------


class TestOneshotRecording:
    def test_anthropic_shaped_usage_is_recorded_and_priced(self, monkeypatch, priced):
        calls = []
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: calls.append(kw) or True)
        result = {"usage": {
            "prompt_tokens": 6, "completion_tokens": 100, "total_tokens": 14_106,
            "cache_creation_input_tokens": 10_000, "cache_read_input_tokens": 4_000,
        }}
        oneshot_mod._record_oneshot_usage("anthropic", "claude-x", result, None, "run1")
        [ev] = calls
        assert ev["cache_creation_input_tokens"] == 10_000
        assert ev["cache_read_input_tokens"] == 4_000
        assert ev["prompt_tokens"] == 6
        assert ev["estimated_cost"] == pytest.approx(_cost(6, 100, 10_000, 4_000))

    def test_openai_shaped_usage_bills_the_cached_part_at_the_cached_rate(self, monkeypatch, priced):
        calls = []
        monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: calls.append(kw) or True)
        sdk = SimpleNamespace(
            prompt_tokens=1_000, completion_tokens=50, total_tokens=1_050,
            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
        )
        oneshot_mod._record_oneshot_usage(
            "openai", "gpt-x", {"usage": oneshot_usage_dict_from_sdk(sdk)}, None, "run2",
        )
        [ev] = calls
        assert (ev["prompt_tokens"], ev["cache_read_input_tokens"]) == (200, 800)
        assert ev["estimated_cost"] == pytest.approx(_cost(200, 50, 0, 800))
        # Cheaper than the old behaviour: all 1,000 at the full input rate.
        assert ev["estimated_cost"] < _cost(1_000, 50, 0, 0)

    def test_the_wire_usage_keeps_its_three_keys_and_historical_prompt_count(self):
        sdk = SimpleNamespace(
            prompt_tokens=1_000, completion_tokens=50, total_tokens=1_050,
            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
        )
        usage = oneshot_mod.OneshotUsage(**oneshot_usage_dict_from_sdk(sdk))
        # `/v1/oneshot` is a stable contract: prompt_tokens still includes cached input.
        assert usage.model_dump() == {
            "prompt_tokens": 1_000, "completion_tokens": 50, "total_tokens": 1_050,
        }

    def test_a_provider_without_cache_returns_the_exact_old_dict(self):
        sdk = SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15)
        assert oneshot_usage_dict_from_sdk(sdk) == {
            "prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15,
        }


# ---------------------------------------------------------------------------
# OpenAI / Gemini report cached input INSIDE the prompt count: normalize it
# ---------------------------------------------------------------------------


class TestProvidersNormalizeCachedInput:
    def test_chat_completions(self, priced):
        sdk = SimpleNamespace(
            prompt_tokens=1_000, completion_tokens=50, total_tokens=1_050,
            prompt_tokens_details=SimpleNamespace(cached_tokens=800),
        )
        u = FakeChatProvider()._parse_usage(sdk)
        assert (u.prompt_tokens, u.cache_read_input_tokens, u.cache_creation_input_tokens) == (200, 800, 0)
        assert u.total_tokens == 1_050
        assert price_usage(u, "m", "p") == pytest.approx(_cost(200, 50, 0, 800))
        assert price_usage(u, "m", "p") < _cost(1_000, 50, 0, 0)

    @pytest.mark.parametrize("details", [None, SimpleNamespace(cached_tokens=None), {}, {"cached_tokens": None}])
    def test_chat_completions_tolerates_absent_or_none_details(self, details):
        sdk = SimpleNamespace(
            prompt_tokens=100, completion_tokens=5, total_tokens=105,
            prompt_tokens_details=details,
        )
        u = FakeChatProvider()._parse_usage(sdk)
        assert (u.prompt_tokens, u.cache_read_input_tokens) == (100, 0)

    def test_chat_completions_details_as_a_dict(self):
        sdk = SimpleNamespace(
            prompt_tokens=100, completion_tokens=5, total_tokens=105,
            prompt_tokens_details={"cached_tokens": 60},
        )
        u = FakeChatProvider()._parse_usage(sdk)
        assert (u.prompt_tokens, u.cache_read_input_tokens) == (40, 60)

    def test_cached_count_never_exceeds_the_prompt(self):
        sdk = SimpleNamespace(
            prompt_tokens=100, completion_tokens=5, total_tokens=105,
            prompt_tokens_details=SimpleNamespace(cached_tokens=999),
        )
        u = FakeChatProvider()._parse_usage(sdk)
        assert (u.prompt_tokens, u.cache_read_input_tokens) == (0, 100)

    def test_responses_api(self, priced):
        sdk = SimpleNamespace(
            input_tokens=1_000, output_tokens=50,
            input_tokens_details=SimpleNamespace(cached_tokens=900),
        )
        u = ResponsesHandler.parse_usage(sdk)
        assert (u.prompt_tokens, u.cache_read_input_tokens, u.total_tokens) == (100, 900, 1_050)
        assert price_usage(u, "m", "p") < _cost(1_000, 50, 0, 0)

    def test_responses_api_without_details(self):
        u = ResponsesHandler.parse_usage(SimpleNamespace(input_tokens=10, output_tokens=2))
        assert (u.prompt_tokens, u.cache_read_input_tokens, u.total_tokens) == (10, 0, 12)

    def test_gemini(self, priced):
        meta = SimpleNamespace(
            prompt_token_count=1_000, candidates_token_count=30, thoughts_token_count=20,
            total_token_count=1_050, cached_content_token_count=700,
        )
        u = GeminiProvider._parse_usage(None, meta)
        assert (u.prompt_tokens, u.cache_read_input_tokens) == (300, 700)
        assert (u.completion_tokens, u.total_tokens) == (50, 1_050)
        assert price_usage(u, "m", "p") < _cost(1_000, 50, 0, 0)

    def test_gemini_without_cache_field(self):
        meta = SimpleNamespace(
            prompt_token_count=10, candidates_token_count=3, thoughts_token_count=0,
            total_token_count=13,
        )
        u = GeminiProvider._parse_usage(None, meta)
        assert (u.prompt_tokens, u.cache_read_input_tokens) == (10, 0)

    def test_gemini_oneshot_wire_keeps_the_provider_prompt_count(self):
        stats = UsageStats(prompt_tokens=300, completion_tokens=50, total_tokens=1_050,
                           cache_read_input_tokens=700)
        d = oneshot_usage_dict_from_stats(stats)
        assert d["prompt_tokens"] == 1_000
        assert d["uncached_prompt_tokens"] == 300


# ---------------------------------------------------------------------------
# Stored usage: old files without cache keys still load
# ---------------------------------------------------------------------------


class TestStorage:
    def test_old_usage_events_lines_read_back_with_zero_cache(self, tmp_path):
        line = {"v": 1, "ts": "2099-01-01T00:00:00", "provider": "p", "model": "m",
                "tier": "chat", "prompt_tokens": 10, "completion_tokens": 5,
                "estimated_cost": 0.5, "owner": None, "run_id": None}
        (tmp_path / "usage-events.jsonl").write_text(json.dumps(line) + "\n", encoding="utf-8")
        events, skipped = read_usage_events(usage_dir=tmp_path)
        assert skipped == 0
        assert (events[0].cache_creation_input_tokens, events[0].cache_read_input_tokens) == (0, 0)
        assert events[0].total_tokens == 15

    def test_new_events_round_trip_and_summarize(self, tmp_path):
        assert record_usage(
            provider="p", model="m", tier="task", prompt_tokens=6, completion_tokens=100,
            estimated_cost=0.1, cache_creation_input_tokens=10_000,
            cache_read_input_tokens=4_000, usage_dir=tmp_path,
        )
        summary = summarize_usage(usage_dir=tmp_path)
        assert summary["cache_creation_input_tokens"] == 10_000
        assert summary["cache_read_input_tokens"] == 4_000
        assert summary["total_tokens"] == 6 + 100 + 10_000 + 4_000
        assert summary["by_tier"]["task"]["cache_read_input_tokens"] == 4_000
        # The keys ppxai-sre's reader depends on are still present.
        assert {"by_tier", "by_model", "event_count", "skipped_lines"} <= set(summary)

    def test_a_cache_only_event_is_not_dropped(self, tmp_path):
        assert record_usage(
            provider="p", model="m", tier="chat", prompt_tokens=0, completion_tokens=0,
            estimated_cost=0.0, cache_read_input_tokens=500, usage_dir=tmp_path,
        )

    def test_old_usage_json_aggregates_without_cache_keys(self, tmp_path):
        record = {
            "session_id": "s", "started_at": "2099-01-01T00:00:00", "ended_at": "2099-01-01T01:00:00",
            "usage_by_model": {"p/m": {"prompt_tokens": 10, "completion_tokens": 5, "estimated_cost": 0.2}},
            "total_cost": 0.2, "total_tokens": 15, "message_count": 1,
        }
        (tmp_path / "usage.json").write_text(
            json.dumps({"version": 1, "sessions": [record]}), encoding="utf-8")
        report = UsageStorage(usage_dir=tmp_path).get_usage_report("all")
        assert report["prompt_tokens"] == 10
        assert report["cache_read_input_tokens"] == 0
        assert report["by_model"]["p/m"]["total_tokens"] == 15

    def test_cache_keys_flow_into_the_usage_report(self, tmp_path):
        record = {
            "session_id": "s", "started_at": "2099-01-01T00:00:00", "ended_at": "2099-01-01T01:00:00",
            "usage_by_model": {"p/m": {"prompt_tokens": 6, "completion_tokens": 100,
                                       "cache_creation_input_tokens": 10_000,
                                       "cache_read_input_tokens": 4_000, "estimated_cost": 0.2}},
            "total_cost": 0.2, "total_tokens": 14_106, "message_count": 1,
        }
        (tmp_path / "usage.json").write_text(
            json.dumps({"version": 1, "sessions": [record]}), encoding="utf-8")
        report = UsageStorage(usage_dir=tmp_path).get_usage_report("all")
        assert report["cache_read_input_tokens"] == 4_000
        assert report["by_model"]["p/m"]["total_tokens"] == 14_106

    def test_a_saved_session_round_trips_cache_tokens(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path)
        session.update_usage(_anthropic_usage(), "p", "m")
        name = session.save("cache-rt")

        loaded = SessionManager(sessions_dir=tmp_path)
        assert loaded.load(name)
        assert loaded.usage.cache_read_input_tokens == 4_000
        assert loaded.usage_by_model["p/m"].cache_creation_input_tokens == 10_000

    def test_a_session_saved_before_cache_keys_existed_loads_with_zeros(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path)
        session.update_usage(UsageStats(prompt_tokens=40, completion_tokens=10, total_tokens=50), "p", "m")
        name = session.save("old-shape")

        path = next(tmp_path.rglob("*.json"))
        data = json.loads(path.read_text(encoding="utf-8"))
        for block in (data["usage"], *data["usage"]["by_model"].values()):
            block.pop("cache_creation_input_tokens", None)
            block.pop("cache_read_input_tokens", None)
        path.write_text(json.dumps(data), encoding="utf-8")

        loaded = SessionManager(sessions_dir=tmp_path)
        assert loaded.load(name)
        assert (loaded.usage.prompt_tokens, loaded.usage.cache_read_input_tokens) == (40, 0)
        assert loaded.usage_by_model["p/m"].cache_creation_input_tokens == 0


# ---------------------------------------------------------------------------
# Display: /usage and /cost text carry the cached breakdown
# ---------------------------------------------------------------------------


class TestDisplay:
    def test_input_cell_breaks_out_cached_tokens(self):
        cell = tools_cmd._input_cell({
            "prompt_tokens": 477, "cache_read_input_tokens": 48_100,
            "cache_creation_input_tokens": 4_000,
        })
        assert cell == "52,577 (52,100 cached)"

    def test_input_cell_is_unchanged_without_cache(self):
        assert tools_cmd._input_cell({"prompt_tokens": 1_200}) == "1,200"

    def test_session_display_dict_carries_cache_fields(self, tmp_path):
        session = SessionManager(sessions_dir=tmp_path)
        session.update_usage(_anthropic_usage(), "p", "m")
        for mode in ("session", "provider", "model"):
            session.usage_display_mode = mode
            d = session.get_usage_for_display("p", "m")
            assert d["cache_read_input_tokens"] == 4_000
            assert d["cache_creation_input_tokens"] == 10_000


class TestSearchLoopGatewayUsageKeepsItsMeaning:
    """`/v1/oneshot` on the search loop reads its usage from `run_usage`, which
    now splits cached input out. The wire's `prompt_tokens` keeps its
    historical meaning, ALL input, which is what OpenAI-wire and Gemini (the
    providers that ever worked on this path) reported."""

    def _usage(self, data):
        events = [SimpleNamespace(type="run_usage", data=data)]
        registry = SimpleNamespace(read_events=lambda run_id: events)
        _grounding, usage = oneshot_mod._grounding_from_events(registry, "run_000000000000")
        return usage

    def test_cached_input_is_added_back(self):
        usage = self._usage({"prompt_tokens": 200, "completion_tokens": 50,
                             "total_tokens": 1250, "cache_read_input_tokens": 1000,
                             "cache_creation_input_tokens": 0})
        assert (usage.prompt_tokens, usage.completion_tokens, usage.total_tokens) == (1200, 50, 1250)

    def test_no_cache_is_unchanged(self):
        usage = self._usage({"prompt_tokens": 200, "completion_tokens": 50, "total_tokens": 250})
        assert (usage.prompt_tokens, usage.total_tokens) == (200, 250)
