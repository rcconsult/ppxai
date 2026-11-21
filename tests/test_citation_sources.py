"""ADR 0019 step 1: one citation contract — the `Source` type, the per-turn
`SourceLedger`, and a grounded `/run` that keeps its sources.

tai's report: a grounded `/run` (`POST /v1/agent/run` under
`execution.run.grounding: retrieve`) numbered its sources in the prompt and
then dropped them, so the result's `[n]` resolved against nothing, while
`/v1/oneshot` returned `grounding.sources`. The run now carries the same
sources on its meta (`GET /v1/agent/runs/{id}` → `sources`) and announces
them as an `agent_run_sources` event.

No test here reaches the network: backends and providers are fakes.
"""

from __future__ import annotations

import asyncio
import dataclasses
import re
import time

import pytest

pytest.importorskip("fastapi")
pytest.importorskip("httpx")

from fastapi import FastAPI
from fastapi.testclient import TestClient

import ppxai.engine as engine_pkg
import ppxai.server.state as state
from ppxai.config import PROVIDERS
from ppxai.config import execution as exec_mod
from ppxai.config.prompts import DEFAULT_SYSTEM_PROMPTS
from ppxai.engine import EngineClient, task_runner
from ppxai.engine import chat as chat_mod
from ppxai.engine.agent_runs import AgentRunRegistry, FilesystemAgentRunStore, RunMeta
from ppxai.engine.providers.wire import get_handler
from ppxai.engine.search.grounding import Retrieval, grounded_prompt
from ppxai.engine.search.types import SearchResult
from ppxai.engine.session import SessionManager
from ppxai.engine.sources import Source, SourceLedger, current_ledger, install_ledger
from ppxai.engine.task_backend import InProcessTaskBackend
from ppxai.engine.tools.base import FunctionTool
from ppxai.engine.tools.builtin import web as web_mod
from ppxai.engine.tools.builtin.web_premium import _format_search_result
from ppxai.engine.types import Event, EventType, Message, ToolUsage
from ppxai.server.routes import agent_v1
from ppxai.server.routes import oneshot as oneshot_mod


def _result(citations=("https://a", "https://b"), titles=(), backend="perplexity"):
    usage = ToolUsage(call_count=1, tokens_in=1, tokens_out=1, estimated_cost=0.0,
                      provider=backend)
    return SearchResult(backend=backend, answer="The answer.", citations=list(citations),
                        usage=usage, titles=list(titles))


# ---------------------------------------------------------------------------
# The ledger
# ---------------------------------------------------------------------------


class TestSourceLedger:

    def test_numbers_start_at_one_and_follow_arrival(self):
        ledger = SourceLedger()
        assert ledger.add("https://a").n == 1
        assert ledger.add("https://b", "b.com", backend="gemini", query="q").n == 2
        assert [s.n for s in ledger.sources] == [1, 2]
        assert len(ledger) == 2

    def test_a_repeated_url_keeps_its_first_number(self):
        ledger = SourceLedger()
        first = ledger.add("https://a", "first title")
        ledger.add("https://b")
        again = ledger.add("https://a", "another title")
        assert again is first and again.n == 1 and again.title == "first title"
        assert len(ledger) == 2

    def test_an_empty_title_is_none(self):
        assert SourceLedger().add("https://a", "").title is None

    def test_rows_round_trip_and_tolerate_unknown_keys(self):
        ledger = SourceLedger()
        ledger.add("https://a", "a.com", backend="gemini", query="q")
        rows = ledger.to_dicts()
        assert rows == [{"n": 1, "url": "https://a", "title": "a.com",
                         "backend": "gemini", "query": "q"}]
        assert Source.from_dict({**rows[0], "from_a_newer_writer": 1}) == ledger.sources[0]


# ---------------------------------------------------------------------------
# Retrieval grounding numbers from the ledger
# ---------------------------------------------------------------------------


class TestGroundedPromptNumbersFromTheLedger:

    def _retrieval(self, **kw):
        return Retrieval(searched=True, query="Q?", result=_result(**kw))

    def test_without_a_ledger_numbering_is_unchanged(self):
        text = grounded_prompt("Q?", self._retrieval(), max_chars=1000)
        assert "[1] https://a" in text and "[2] https://b" in text

    def test_the_ledger_receives_every_listed_source(self):
        ledger = SourceLedger()
        grounded_prompt("Q?", self._retrieval(titles=("a.com", "")), max_chars=1000,
                        ledger=ledger)
        assert ledger.to_dicts() == [
            {"n": 1, "url": "https://a", "title": "a.com", "backend": "perplexity",
             "query": "Q?"},
            {"n": 2, "url": "https://b", "title": None, "backend": "perplexity",
             "query": "Q?"},
        ]

    def test_a_later_search_in_the_turn_continues_the_numbers(self):
        ledger = SourceLedger()
        ledger.add("https://earlier")
        ledger.add("https://a")  # already cited earlier in the turn
        text = grounded_prompt("Q?", self._retrieval(citations=("https://a", "https://c")),
                               max_chars=1000, ledger=ledger)
        assert "[2] https://a" in text and "[3] https://c" in text
        assert [s.url for s in ledger.sources] == ["https://earlier", "https://a", "https://c"]

    def test_every_number_in_the_prompt_resolves_in_the_ledger(self):
        ledger = SourceLedger()
        text = grounded_prompt("Q?", self._retrieval(), max_chars=1000, ledger=ledger)
        cited = {int(n) for n in re.findall(r"^\[(\d+)\] ", text, flags=re.M)}
        assert cited == {s.n for s in ledger.sources}


# ---------------------------------------------------------------------------
# RunMeta: the field is additive
# ---------------------------------------------------------------------------


class TestRunMetaSources:

    def test_a_meta_written_before_the_field_loads_empty(self):
        meta = RunMeta.from_dict({"run_id": "r1", "task": "t"})
        assert meta.sources == []

    def test_record_sources_persists_and_announces(self, tmp_path):
        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        meta = reg.start_run(task="t", kind="oneshot", tools=[])
        ledger = SourceLedger()
        ledger.add("https://a")
        reg.record_sources(meta, ledger.to_dicts())
        assert reg.get_run(meta.run_id).sources == ledger.to_dicts()
        events = [e for e in reg.read_events(meta.run_id) if e.type == "agent_run_sources"]
        assert len(events) == 1
        assert events[0].category == "result"
        assert events[0].data == {"sources": ledger.to_dicts()}

    def test_an_unchanged_ledger_records_nothing_new(self, tmp_path):
        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        meta = reg.start_run(task="t", kind="oneshot", tools=[])
        ledger = SourceLedger()
        ledger.add("https://a")
        reg.record_sources(meta, ledger.to_dicts())
        reg.record_sources(meta, ledger.to_dicts())
        ledger.add("https://b")
        reg.record_sources(meta, ledger.to_dicts())
        events = [e for e in reg.read_events(meta.run_id) if e.type == "agent_run_sources"]
        assert [len(e.data["sources"]) for e in events] == [1, 2]

    def test_an_empty_ledger_records_nothing(self, tmp_path):
        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        meta = reg.start_run(task="t", kind="oneshot", tools=[])
        reg.record_sources(meta, SourceLedger().to_dicts())
        assert not [e for e in reg.read_events(meta.run_id) if e.type == "agent_run_sources"]


# ---------------------------------------------------------------------------
# The route: tai's report
# ---------------------------------------------------------------------------


@pytest.fixture
def grounded_run(tmp_path, monkeypatch):
    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    monkeypatch.setattr(state, "_agent_run_registry", reg)
    monkeypatch.setattr(exec_mod, "get_execution_collect", lambda: "no")
    monkeypatch.setattr(exec_mod, "get_execution_run_config",
                        lambda: {"web_search": False, "grounding": True})
    monkeypatch.setattr(oneshot_mod, "get_execution_egress_ceiling", lambda: None)
    monkeypatch.setattr(oneshot_mod, "record_usage", lambda **kw: True)
    prompts: list[str] = []

    class _P:
        def oneshot(self, *, prompt, model, system=None, **kw):
            prompts.append(prompt)
            return {"content": "It changed [1], see also [2].", "finish_reason": "stop"}

    async def fake_retrieve(prompt, provider_name, egress_allows=None):
        return Retrieval(searched=True, query=prompt,
                         result=_result(titles=("a.com", "b.com"), backend="gemini"))

    monkeypatch.setattr(agent_v1, "_build_provider", lambda name: _P())
    monkeypatch.setattr(oneshot_mod, "retrieve", fake_retrieve)

    app = FastAPI()
    app.include_router(agent_v1.router)
    client = TestClient(app)

    def run(mode="retrieve"):
        monkeypatch.setattr(exec_mod, "get_execution_run_grounding_mode", lambda: mode)
        resp = client.post("/v1/agent/run",
                           json={"task": "what changed?", "provider": "p", "model": "m"})
        assert resp.status_code == 200, resp.text
        run_id = resp.json()["run_id"]
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            body = client.get(f"/v1/agent/runs/{run_id}").json()
            if body["status"] == "completed":
                return run_id, body, prompts[-1], reg
            time.sleep(0.02)
        raise AssertionError(f"run did not complete: {body}")

    return run


class TestAGroundedRunKeepsItsSources:

    def test_the_run_meta_carries_the_sources(self, grounded_run):
        _, body, _, _ = grounded_run()
        assert body["result"] == "It changed [1], see also [2]."
        assert body["sources"] == [
            {"n": 1, "url": "https://a", "title": "a.com", "backend": "gemini",
             "query": "what changed?"},
            {"n": 2, "url": "https://b", "title": "b.com", "backend": "gemini",
             "query": "what changed?"},
        ]

    def test_the_numbers_the_model_saw_are_the_numbers_on_the_run(self, grounded_run):
        _, body, prompt, _ = grounded_run()
        in_prompt = dict(re.findall(r"^\[(\d+)\] \S+ (\S+)$", prompt, flags=re.M))
        on_run = {str(s["n"]): s["url"] for s in body["sources"]}
        assert in_prompt == on_run

    def test_the_sources_are_announced_before_the_result(self, grounded_run):
        run_id, _, _, reg = grounded_run()
        types = [e.type for e in reg.read_events(run_id)]
        assert "agent_run_sources" in types
        assert types.index("agent_run_sources") < types.index("agent_run_complete")

    def test_a_closed_book_run_has_no_sources(self, grounded_run):
        run_id, body, prompt, reg = grounded_run(mode="off")
        assert body["sources"] == []
        assert not prompt.startswith("<web_search_results")
        assert "agent_run_sources" not in [e.type for e in reg.read_events(run_id)]


# ===========================================================================
# Step 2: the web_search tool numbers from the turn's ledger; /task and
# /run-with-web_search keep their sources on the run.
# ===========================================================================



@pytest.fixture
def turn_ledger():
    """A ledger installed for the test, the way chat.py installs it for a
    tool call; restored afterwards so no other test inherits it."""
    ledger = SourceLedger()
    prior = install_ledger(ledger)
    try:
        yield ledger
    finally:
        install_ledger(prior)


class TestTheSearchToolNumbersFromTheLedger:

    def test_outside_a_turn_it_numbers_from_one(self):
        assert current_ledger() is None
        text = _format_search_result("perplexity", "Answer.", ["https://a", "https://b"])
        assert "Sources (cite as [n]):\n[1] https://a\n[2] https://b\n" in text

    def test_titles_sit_beside_their_urls(self):
        text = _format_search_result("gemini", "A.", ["https://r1"], titles=["a.com"])
        assert "[1] a.com https://r1" in text

    def test_no_citations_no_source_block(self):
        assert "Sources" not in _format_search_result("perplexity", "A.", [])

    def test_a_second_search_in_the_turn_numbers_on(self, turn_ledger):
        first = _format_search_result("perplexity", "A.", ["https://a", "https://b"], query="q1")
        second = _format_search_result("perplexity", "B.", ["https://b", "https://c"], query="q2")
        assert "[1] https://a" in first and "[2] https://b" in first
        assert "[2] https://b" in second and "[3] https://c" in second
        assert [(s.n, s.url, s.query) for s in turn_ledger.sources] == [
            (1, "https://a", "q1"), (2, "https://b", "q1"), (3, "https://c", "q2"),
        ]

    def test_duckduckgo_numbers_from_the_same_ledger(self, turn_ledger):
        _format_search_result("perplexity", "A.", ["https://a"])
        text = web_mod._format_ddg_results(
            "q", [("T1", "https://a", "s1"), ("T2", "https://d", "s2")]
        )
        assert "[1] T1\n   URL: https://a" in text
        assert "[2] T2\n   URL: https://d" in text
        assert turn_ledger.sources[1].backend == "duckduckgo"

    def test_duckduckgo_with_no_results(self):
        assert "No results found for 'q'" in web_mod._format_ddg_results("q", [])


def _run_with_stub_engine(tmp_path, monkeypatch, searches, meta_sources=None):
    """Drive `build_task_runner` with a stub engine whose chat() runs one
    search per entry in `searches` through the ledger the runner passed,
    the way the real tool loop does."""
    reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
    seen: dict = {}

    class _TM:
        max_iterations = 3

        def register_tool(self, tool):
            pass

        def get_tool(self, name):
            return None

    class _StubEngine:
        def __init__(self):
            self.tool_manager = _TM()

        def set_provider(self, p):
            pass

        def set_model(self, m):
            pass

        def set_working_dir(self, d):
            pass

        def enable_tools(self):
            pass

        async def chat(self, task, stream=False, sources=None, **_kw):
            seen["ledger"] = sources
            for urls in searches:
                prior = install_ledger(sources)
                try:
                    out = _format_search_result("perplexity", "A.", list(urls))
                finally:
                    install_ledger(prior)
                yield Event(type=EventType.TOOL_RESULT, data={"tool": "web_search", "result": out})
            yield Event(type=EventType.STREAM_END, data="answer [1]")

    monkeypatch.setattr(task_runner, "EngineClient", _StubEngine, raising=False)
    meta = reg.start_run(task="t", kind="task", tools=["web_search"])
    if meta_sources is not None:
        meta.sources = meta_sources
    runner = task_runner.build_task_runner(
        reg, provider_name="p", model="m", task="t", tools=["web_search"],
        allow_outbound=[],
    )

    async def go():
        reg.run_in_background(meta, runner)
        for _ in range(250):
            if reg.get_run(meta.run_id).status not in ("pending", "running"):
                return
            await asyncio.sleep(0.02)

    asyncio.run(go())
    return reg, meta, seen


class TestATaskRunKeepsItsSources:

    def test_every_search_lands_on_the_run(self, tmp_path, monkeypatch):
        reg, meta, _ = _run_with_stub_engine(
            tmp_path, monkeypatch, [("https://a", "https://b"), ("https://b", "https://c")]
        )
        run = reg.get_run(meta.run_id)
        assert run.status == "completed", run.error
        assert [(s["n"], s["url"]) for s in run.sources] == [
            (1, "https://a"), (2, "https://b"), (3, "https://c"),
        ]

    def test_the_run_announces_each_growth(self, tmp_path, monkeypatch):
        reg, meta, _ = _run_with_stub_engine(
            tmp_path, monkeypatch, [("https://a",), ("https://a",), ("https://b",)]
        )
        events = [e for e in reg.read_events(meta.run_id) if e.type == "agent_run_sources"]
        # The repeated URL changes nothing, so it announces nothing.
        assert [len(e.data["sources"]) for e in events] == [1, 2]

    def test_a_resumed_run_keeps_its_numbers(self, tmp_path, monkeypatch):
        earlier = [{"n": 1, "url": "https://old", "title": None, "backend": "perplexity",
                    "query": None}]
        reg, meta, seen = _run_with_stub_engine(
            tmp_path, monkeypatch, [("https://old", "https://new")], meta_sources=earlier,
        )
        assert [(s["n"], s["url"]) for s in reg.get_run(meta.run_id).sources] == [
            (1, "https://old"), (2, "https://new"),
        ]
        assert isinstance(seen["ledger"], SourceLedger)

    def test_a_run_that_never_searched_has_none(self, tmp_path, monkeypatch):
        reg, meta, _ = _run_with_stub_engine(tmp_path, monkeypatch, [])
        assert reg.get_run(meta.run_id).sources == []


# ===========================================================================
# Step 3: chat — one ledger per turn, STREAM_END metadata, the transcript.
# ===========================================================================



def _scripted_engine(fake_providers, rounds):
    """A real EngineClient on a fake wire whose replies are `rounds`: each
    entry is either ("tool", name, args) or ("text", reply). Its web_search
    tool returns a formatted result over canned URLs per query."""

    engine = EngineClient()
    assert engine.set_provider("openai")
    engine.set_model(PROVIDERS["openai"].get("default_model") or next(iter(PROVIDERS["openai"]["models"])))
    engine.enable_tools()

    canned = {
        "q1": ["https://a", "https://b"],
        "q2": ["https://b", "https://c"],
    }

    async def fake_search(query: str = "", num_results: int = 5, **_kw):
        return _format_search_result("perplexity", f"About {query}.", canned.get(query, []),
                                     query=query)

    engine.tool_manager.register_tool(FunctionTool(
        name="web_search", description="search",
        parameters={"type": "object", "properties": {"query": {"type": "string"}},
                    "required": ["query"]},
        handler=fake_search,
    ))

    script = list(rounds)
    tool_results: list[str] = []

    async def chat(messages, model, stream=False, tools=None):
        for m in messages:
            if m.role == "tool" and m.text_content() not in tool_results:
                tool_results.append(m.text_content())
        step = script.pop(0) if script else ("text", "done")
        yield Event(EventType.STREAM_START, None)
        if step[0] == "tool":
            call = {"tool": step[1], "arguments": step[2],
                    "tool_call_id": f"c{len(script)}", "native": True}
            yield Event(EventType.TOOL_CALL, call)
            yield Event(EventType.STREAM_END, "", {"tool_calls": [call]})
        else:
            yield Event(EventType.STREAM_END, step[1])

    engine.provider.chat = chat
    return engine, tool_results


def _turn(engine, text):
    async def go():
        return [e async for e in engine.chat(text, stream=False)]
    return asyncio.run(go())


class TestAChatTurnKeepsItsSources:

    @pytest.fixture
    def engine(self, fake_providers):
        engine, tool_results = _scripted_engine(fake_providers, [
            ("tool", "web_search", {"query": "q1"}),
            ("tool", "web_search", {"query": "q2"}),
            ("text", "A [1], B [2], C [3]."),
            ("text", "No search this time."),
        ])
        engine._tool_results = tool_results
        return engine

    def test_two_searches_share_one_numbering(self, engine):
        _turn(engine, "first question")
        results = [r for r in engine._tool_results if "Sources" in r]
        assert len(results) == 2, engine._tool_results
        assert "[1] https://a" in results[0] and "[2] https://b" in results[0]
        assert "[2] https://b" in results[1] and "[3] https://c" in results[1]

    def test_stream_end_carries_the_sources(self, engine):
        events = _turn(engine, "first question")
        end = [e for e in events if e.type == EventType.STREAM_END][-1]
        assert [(s["n"], s["url"]) for s in end.metadata["sources"]] == [
            (1, "https://a"), (2, "https://b"), (3, "https://c"),
        ]

    def test_the_answer_keeps_them_in_the_transcript(self, engine):
        _turn(engine, "first question")
        answer = [m for m in engine.session.messages if m.role == "assistant"][-1]
        assert answer.text_content() == "A [1], B [2], C [3]."
        assert [s.url for s in answer.sources] == ["https://a", "https://b", "https://c"]
        others = [m for m in engine.session.messages if m is not answer]
        assert all(not m.sources for m in others)

    def test_numbering_restarts_each_turn(self, engine):
        _turn(engine, "first question")
        events = _turn(engine, "second question")
        end = [e for e in events if e.type == EventType.STREAM_END][-1]
        assert "sources" not in (end.metadata or {})
        assert len(engine.turn_sources) == 0
        # The first turn's answer still has its own.
        first = [m for m in engine.session.messages if m.role == "assistant" and m.sources]
        assert len(first) == 1

    @pytest.mark.parametrize("wire", ["chat_completions", "responses", "generate_content", "messages"])
    def test_the_sources_are_never_sent_to_the_model(self, wire):
        """Every wire handler serializes `content` only: a stored answer's
        sources never reach the provider on a later turn."""
        pytest.importorskip("google.genai") if wire == "generate_content" else None
        pytest.importorskip("anthropic") if wire == "messages" else None

        marker = "https://only-in-sources.example"
        msgs = [Message("user", "q"),
                Message("assistant", "A [1].", sources=[Source(n=1, url=marker)]),
                Message("user", "and?")]
        out = get_handler(wire).convert_messages(msgs)
        assert marker not in repr(out)


class TestTheTranscriptStoresSources:

    def _session(self, tmp_path):
        return SessionManager(sessions_dir=tmp_path / "sessions")

    def test_round_trip(self, tmp_path):
        s = self._session(tmp_path)
        src = [Source(n=1, url="https://a", title="a.com", backend="gemini", query="q")]
        d = s._serialize_message(Message("assistant", "A [1].", sources=src))
        assert d["sources"] == [src[0].to_dict()]
        back = s._deserialize_message(d, schema_version=2)
        assert back.sources == src

    def test_a_message_without_sources_keeps_its_old_shape(self, tmp_path):
        s = self._session(tmp_path)
        d = s._serialize_message(Message("assistant", "plain"))
        assert "sources" not in d
        assert s._deserialize_message(d, schema_version=2).sources == []

    def test_malformed_rows_never_break_a_load(self, tmp_path):
        s = self._session(tmp_path)
        d = {"role": "assistant", "content": "x",
             "sources": [{"n": "one", "url": "https://a"}, {"title": "no url"}, "junk",
                         {"n": 2, "url": "https://ok"}]}
        assert [x.url for x in s._deserialize_message(d, schema_version=2).sources] == [
            "https://ok"]
        d["sources"] = "not a list"
        assert s._deserialize_message(d, schema_version=2).sources == []

    def test_save_and_load_keep_them(self, tmp_path):
        s = self._session(tmp_path)
        s.add_message(Message("user", "q"))
        s.add_message(Message("assistant", "A [1].",
                              sources=[Source(n=1, url="https://a", title="a.com")]))
        name = s.save("cites")
        t = self._session(tmp_path)
        assert t.load(name)
        assert t.messages[-1].sources == [Source(n=1, url="https://a", title="a.com")]

    def test_the_export_lists_them(self, tmp_path):
        s = self._session(tmp_path)
        s.add_message(Message("assistant", "A [1].",
                              sources=[Source(n=1, url="https://a", title="a.com")]))
        text = s.export("e.md").read_text(encoding="utf-8")
        assert "**Sources:**\n\n1. [a.com](<https://a>)" in text


class TestAMergedRunBringsItsSources:

    def test_the_in_process_merge(self, tmp_path):

        reg = AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))
        session = SessionManager(sessions_dir=tmp_path / "sessions")
        meta = reg.start_run(task="t", kind="oneshot", tools=[],
                             session_id=session.session_name)
        rows = [{"n": 1, "url": "https://a", "title": None, "backend": "gemini", "query": "t"}]
        reg.record_sources(meta, rows)
        reg.finish_run(meta, status="completed", result="R [1].")
        backend = InProcessTaskBackend.__new__(InProcessTaskBackend)
        backend.registry = reg
        backend._session_provider = lambda: session
        ok, detail = backend.merge_result(meta.run_id)
        assert ok, detail
        assert session.messages[-1].sources == [Source.from_dict(rows[0])]


# ===========================================================================
# Gemini's grounding redirects resolve to the real pages (owner decision
# 2026-11-21): the stored link must still open after the redirect expires.
# ===========================================================================

import httpx  # noqa: E402

from ppxai.engine.search import redirects as redirects_mod  # noqa: E402
from ppxai.engine.search.resolver import BACKEND_HOSTS, BackendResolution  # noqa: E402
from ppxai.engine.tools.builtin import web_premium  # noqa: E402

_R = "https://vertexaisearch.cloud.google.com/grounding-api-redirect/"


@pytest.fixture
def redirect_server(monkeypatch):
    """A mock transport for the redirect host; records every request."""
    seen: list[str] = []
    answers: dict[str, httpx.Response] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(str(request.url))
        return answers.get(str(request.url), httpx.Response(404))

    monkeypatch.setattr(redirects_mod, "_make_client",
                        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(redirects_mod, "_CACHE", type(redirects_mod._CACHE)())
    return seen, answers


def _resolve(urls, egress_allows=None):
    return asyncio.run(redirects_mod.resolve_redirects(urls, egress_allows))


class TestGroundingRedirectsResolve:

    def test_a_redirect_becomes_its_target(self, redirect_server):
        seen, answers = redirect_server
        answers[_R + "a"] = httpx.Response(302, headers={"location": "https://python.org/x"})
        assert _resolve([_R + "a", "https://plain.example/"]) == [
            "https://python.org/x", "https://plain.example/"]
        assert seen == [_R + "a"]  # the plain link is never looked up

    def test_the_target_is_never_fetched(self, redirect_server):
        seen, answers = redirect_server
        answers[_R + "a"] = httpx.Response(302, headers={"location": "https://python.org/x"})
        _resolve([_R + "a"])
        assert all(u.startswith(_R) for u in seen)

    def test_a_failed_lookup_keeps_the_redirect(self, redirect_server):
        _, answers = redirect_server
        answers[_R + "ok"] = httpx.Response(200)  # no redirect
        answers[_R + "bad"] = httpx.Response(302, headers={"location": "javascript:alert(1)"})
        assert _resolve([_R + "ok", _R + "bad", _R + "404"]) == [
            _R + "ok", _R + "bad", _R + "404"]

    def test_a_network_error_keeps_the_redirect(self, monkeypatch):
        def boom(request):
            raise httpx.ConnectError("down")
        monkeypatch.setattr(redirects_mod, "_make_client",
                            lambda: httpx.AsyncClient(transport=httpx.MockTransport(boom)))
        monkeypatch.setattr(redirects_mod, "_CACHE", type(redirects_mod._CACHE)())
        assert _resolve([_R + "a"]) == [_R + "a"]

    def test_outside_the_egress_predicate_nothing_is_contacted(self, redirect_server):
        seen, answers = redirect_server
        answers[_R + "a"] = httpx.Response(302, headers={"location": "https://python.org/x"})
        assert _resolve([_R + "a"], egress_allows=lambda host: False) == [_R + "a"]
        assert seen == []

    def test_a_resolved_link_is_looked_up_once(self, redirect_server):
        seen, answers = redirect_server
        answers[_R + "a"] = httpx.Response(302, headers={"location": "https://python.org/x"})
        _resolve([_R + "a", _R + "a"])
        _resolve([_R + "a"])
        assert seen == [_R + "a"]

    def test_only_the_real_redirect_host_matches(self):
        assert redirects_mod.is_grounding_redirect(_R + "x")
        assert not redirects_mod.is_grounding_redirect("https://vertexaisearch.example/r1")
        assert not redirects_mod.is_grounding_redirect(
            "http://vertexaisearch.cloud.google.com/grounding-api-redirect/x")
        assert not redirects_mod.is_grounding_redirect(
            "https://vertexaisearch.cloud.google.com/other/x")

    def test_the_redirect_host_is_not_a_backend_host(self):
        # Adding it would drop Gemini from every run allowing only the API host.
        assert not any(redirects_mod.REDIRECT_HOST in h for h in BACKEND_HOSTS["gemini"])

    def test_the_web_search_tool_lists_the_real_pages(self, redirect_server, monkeypatch):
        _, answers = redirect_server
        answers[_R + "a"] = httpx.Response(302, headers={"location": "https://python.org/x"})

        class _Gemini:
            async def search(self, query, n):
                return SearchResult(backend="gemini", answer="A.", citations=[_R + "a"],
                                    usage=None, titles=["python.org"])

        monkeypatch.setattr(web_premium, "resolve_web_search_backend",
                            lambda *a, **k: BackendResolution(
                                scope="global", preferred="gemini", strict=False,
                                candidates=("gemini",), egress_hosts=()))
        monkeypatch.setattr(web_premium, "get_backend", lambda _id: _Gemini())
        monkeypatch.setattr(web_premium, "_record_usage", lambda usage: None)
        text = asyncio.run(web_premium.web_search_premium("q"))
        assert "[1] python.org https://python.org/x" in text
        assert _R not in text


# ===========================================================================
# Step 5: no inline-URL prompt; the model cites [n] and the client lists them.
# ===========================================================================

_OLD_CITATION_PROMPTS = ("full URL in parentheses", "markdown links", "so they are clickable")


class TestChatAsksForNumbersNotLinks:

    def test_a_tool_free_turn_sends_no_citation_prompt(self, fake_providers):
        # The old prompt was prepended whenever the provider had native
        # search or citations; give it both and look at what the wire gets.
        engine = EngineClient()
        assert engine.set_provider("openai")
        engine.set_model(PROVIDERS["openai"].get("default_model")
                         or next(iter(PROVIDERS["openai"]["models"])))
        engine.disable_tools()
        engine.provider.capabilities = dataclasses.replace(
            engine.provider.capabilities, citations=True, web_search=True)
        sent: list[list[Message]] = []

        async def chat(messages, model, stream=False, tools=None):
            sent.append(list(messages))
            yield Event(EventType.STREAM_START, None)
            yield Event(EventType.STREAM_END, "An answer.")

        engine.provider.chat = chat
        _turn(engine, "hello")
        assert sent, "the provider was never called"
        texts = [m.text_content() for m in sent[0]]
        assert not any(p in t for t in texts for p in _OLD_CITATION_PROMPTS), texts
        assert [m.role for m in sent[0]] == ["user"]

    def _ctx(self, *, search_tool: bool, native: bool):
        caps = type("Caps", (), {"citations": native, "web_search": native})()

        class _ToolMgr:
            def get_tools_prompt(self, working_dir=None):
                return "TOOLS"

            def get_tool(self, name):
                return object() if (search_tool and name == "web_search") else None

        class _Ctx:
            provider_name = "openai"
            provider = type("P", (), {"capabilities": caps})()
            model = "m"
            tool_manager = _ToolMgr()
            session = type("S", (), {"get_messages": lambda self: []})()
            system_prompt_override = None

            def get_working_dir(self):
                return None

            def get_bootstrap_prompt(self):
                return ""

        return _Ctx()

    @pytest.fixture(autouse=True)
    def _fixed_system_prompt(self, monkeypatch):
        monkeypatch.setattr(chat_mod, "get_system_prompt", lambda p=None: "CFG")
        monkeypatch.setattr(chat_mod, "get_system_prompt_mode", lambda p=None: "prepend")

    def test_with_web_search_the_tool_prompt_asks_for_numbers(self):
        prompt = chat_mod._build_prompt_based_messages(self._ctx(search_tool=True, native=False))[0].content
        assert "cite them by their number, like [1]" in prompt
        assert not any(p in prompt for p in _OLD_CITATION_PROMPTS)

    def test_native_search_alone_gets_no_citation_instruction(self):
        # Native grounding places its own [n] markers (ADR 0019 step 6).
        prompt = chat_mod._build_prompt_based_messages(self._ctx(search_tool=False, native=True))[0].content
        assert "cite them by their number" not in prompt
        assert not any(p in prompt for p in _OLD_CITATION_PROMPTS)

    def test_chat_response_is_gone(self):
        assert not hasattr(engine_pkg, "ChatResponse")
        assert "ChatResponse" not in engine_pkg.__all__

    def test_shipped_prompts_ask_for_numbers(self):
        assert not any(p in t for t in DEFAULT_SYSTEM_PROMPTS.values() for p in _OLD_CITATION_PROMPTS)
