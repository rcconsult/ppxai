"""Option B (docs/analysis-chat-streaming-and-interrupts.md, section C): a
cancel stops a run's model call, instead of waiting for it to finish.

- `RunControl.interruptible` stops waiting the moment the run is cancelled
  and raises `RunCancelledDuringCall` (run ends `cancelled`, not resumable).
- `CallStop` lets the provider abort its request: `openai_compat` streams
  its one-shot request and closes the stream. Checked against a real local
  HTTP server that streams slowly and records the client hanging up.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import functools
import http.server
import json
import threading
import time

import pytest

from ppxai.engine.agent_runs import (
    AgentRunRegistry,
    FilesystemAgentRunStore,
    RunCancelledDuringCall,
    RunControl,
)
from ppxai.engine.call_stop import CallAbortedError, CallStop
from ppxai.engine.providers.openai_compat import OpenAICompatibleProvider

# --- a slow OpenAI-compatible streaming server ------------------------------


class _Server:
    """Streams N content chunks, one every DELAY seconds, then a usage chunk.
    Records how many chunks it wrote and whether the client hung up."""

    def __init__(self, chunks: int = 40, delay: float = 0.1) -> None:
        self.chunks, self.delay = chunks, delay
        self.written = 0
        self.client_hung_up = threading.Event()
        self.first_chunk_sent = threading.Event()
        self.finished = threading.Event()
        self.requests: list[dict] = []
        server = self

        class Handler(http.server.BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"

            def log_message(self, *a):  # quiet
                pass

            def do_POST(self):  # noqa: N802 — http.server's name
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                server.requests.append(body)
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream")
                self.send_header("Transfer-Encoding", "chunked")
                self.end_headers()
                try:
                    for i in range(server.chunks):
                        self._event({"choices": [{"index": 0, "delta": {"content": f"w{i} "},
                                                  "finish_reason": None}]})
                        server.written += 1
                        server.first_chunk_sent.set()
                        time.sleep(server.delay)
                    self._event({"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]})
                    self._event({"choices": [], "usage": {"prompt_tokens": 3, "completion_tokens": 40,
                                                          "total_tokens": 43}})
                    self._raw(b"data: [DONE]\n\n")
                    self.wfile.write(b"0\r\n\r\n")
                    self.wfile.flush()
                    server.finished.set()
                except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                    server.client_hung_up.set()

            def _event(self, payload):
                payload = {"id": "c", "object": "chat.completion.chunk", "created": 0,
                           "model": "served-model", **payload}
                self._raw(f"data: {json.dumps(payload)}\n\n".encode())

            def _raw(self, data: bytes):
                self.wfile.write(f"{len(data):x}\r\n".encode() + data + b"\r\n")
                self.wfile.flush()

        self.httpd = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        # A broken stop leaves a connection open; teardown must not wait on it.
        self.httpd.daemon_threads = True
        self.httpd.block_on_close = False
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/v1"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self):
        self.httpd.shutdown()
        self.httpd.server_close()


@pytest.fixture
def server():
    s = _Server()
    yield s
    s.close()


@pytest.fixture
def provider(server):
    return OpenAICompatibleProvider(
        api_key="test-key", base_url=server.url,
        models={"m": {"name": "m", "description": "test"}}, provider_id="local",
    )


# --- openai_compat: the request is really aborted ---------------------------


class TestOpenAICompatOneshotStoppable:
    def test_without_a_stop_it_returns_the_whole_answer(self, server, provider):
        server.chunks, server.delay = 3, 0.0
        out = provider.oneshot_stoppable(stop=CallStop(), prompt="hi", model="m")
        assert out["content"] == "w0 w1 w2 "
        assert out["finish_reason"] == "stop"
        assert out["model"] == "served-model"
        assert out["usage"] == {"prompt_tokens": 3, "completion_tokens": 40, "total_tokens": 43}
        sent = server.requests[0]
        assert sent["stream"] is True and sent["stream_options"] == {"include_usage": True}
        assert sent["messages"][-1] == {"role": "user", "content": "hi"}

    def test_a_stop_closes_the_connection_mid_answer(self, server, provider):
        stop = CallStop()
        threading.Thread(
            target=lambda: (server.first_chunk_sent.wait(5), stop.stop()), daemon=True
        ).start()
        raised: list[BaseException] = []

        def call():
            try:
                provider.oneshot_stoppable(stop=stop, prompt="hi", model="m")
            except BaseException as exc:  # noqa: BLE001 — recorded for the asserts
                raised.append(exc)

        worker = threading.Thread(target=call, daemon=True)
        worker.start()
        worker.join(2.0)                              # 40 chunks x 0.1 s would be 4 s
        assert not worker.is_alive(), "the stop didn't unblock the read"
        assert len(raised) == 1 and isinstance(raised[0], CallAbortedError)
        assert server.client_hung_up.wait(3), "the server never saw the client hang up"
        assert not server.finished.is_set()
        assert server.written < server.chunks

    def test_stopped_before_it_starts_sends_nothing(self, server, provider):
        stop = CallStop()
        stop.stop()
        with pytest.raises(CallAbortedError):
            provider.oneshot_stoppable(stop=stop, prompt="hi", model="m")
        assert server.requests == []

    def test_a_subclass_overriding_oneshot_keeps_its_own_call(self):
        class Custom(OpenAICompatibleProvider):
            def __init__(self):  # no client: the streaming path would fail
                pass

            def oneshot(self, *, prompt, model, system=None, **kw):
                return {"content": f"custom: {prompt}", "finish_reason": "stop"}

        out = Custom().oneshot_stoppable(stop=CallStop(), prompt="hi", model="m")
        assert out["content"] == "custom: hi"

    def test_plain_oneshot_still_does_not_stream(self, server, provider):
        """`POST /v1/oneshot` keeps `oneshot`: same non-streaming request."""
        request = provider._oneshot_request("hi", "m", None, None, None, None)
        assert request["stream"] is False and "stream_options" not in request


# --- RunControl.interruptible ------------------------------------------------


class TestInterruptible:
    @pytest.mark.asyncio
    async def test_returns_the_call_result(self):
        ctl = RunControl(run_id="r")

        async def call():
            return 42

        assert await ctl.interruptible(call()) == 42

    @pytest.mark.asyncio
    async def test_a_cancel_ends_the_wait_at_once_and_stops_the_call(self):
        ctl = RunControl(run_id="r")
        stop = CallStop()
        slow = asyncio.ensure_future(asyncio.sleep(30))

        async def cancel_soon():
            await asyncio.sleep(0.05)
            ctl.cancel_requested = True
            ctl.cancel_event.set()

        asyncio.ensure_future(cancel_soon())
        t0 = time.monotonic()
        with pytest.raises(RunCancelledDuringCall) as err:
            await ctl.interruptible(slow, stop=stop)
        assert time.monotonic() - t0 < 1.0
        assert stop.stopped
        await asyncio.sleep(0)
        assert slow.cancelled()
        assert err.value.status == "cancelled" and err.value.resumable is False

    @pytest.mark.asyncio
    async def test_already_cancelled_does_not_wait(self):
        ctl = RunControl(run_id="r", cancel_requested=True)
        stop = CallStop()
        with pytest.raises(RunCancelledDuringCall):
            await ctl.interruptible(asyncio.sleep(30), stop=stop)
        assert stop.stopped

    @pytest.mark.asyncio
    async def test_the_run_task_being_cancelled_stops_the_call_too(self):
        ctl = RunControl(run_id="r")
        stop = CallStop()
        outer = asyncio.ensure_future(ctl.interruptible(asyncio.sleep(30), stop=stop))
        await asyncio.sleep(0.02)
        outer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await outer
        assert stop.stopped

    @pytest.mark.asyncio
    async def test_an_abort_that_wins_the_race_is_still_a_cancel(self):
        ctl = RunControl(run_id="r")

        async def call():
            ctl.cancel_requested = True
            raise CallAbortedError("stopped")

        with pytest.raises(RunCancelledDuringCall):
            await ctl.interruptible(call())

    @pytest.mark.asyncio
    async def test_an_abort_without_a_cancel_is_not_hidden(self):
        ctl = RunControl(run_id="r")

        async def call():
            raise CallAbortedError("stopped")

        with pytest.raises(CallAbortedError):
            await ctl.interruptible(call())


# --- the whole path: registry cancel -> run ends -> connection closed --------


@pytest.fixture
def registry(tmp_path):
    return AgentRunRegistry(FilesystemAgentRunStore(tmp_path / "runs"))


@pytest.mark.asyncio
async def test_cancelling_a_run_closes_the_providers_connection(registry, server, provider):
    m = registry.start_run("essay", provider="local", model="m")

    # Its own pool, not to_thread's default one: if the stop were broken the
    # worker would stay blocked, and closing the loop would wait for it.
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    async def runner(meta):
        ctl = registry.get_control(meta.run_id)
        stop = CallStop()
        call = functools.partial(provider.oneshot_stoppable, stop=stop, prompt="essay", model="m")
        result = await ctl.interruptible(
            asyncio.get_running_loop().run_in_executor(pool, call), stop=stop,
        )
        return result["content"]

    try:
        await _cancel_and_check(registry, server, m, runner)
    finally:
        pool.shutdown(wait=False)


async def _cancel_and_check(registry, server, m, runner):
    registry.run_in_background(m, runner)
    await asyncio.to_thread(server.first_chunk_sent.wait, 5)
    t0 = time.monotonic()
    assert registry.cancel_run(m.run_id) is True
    await asyncio.wait_for(asyncio.shield(registry.get_run_task(m.run_id)), 2.0)
    assert time.monotonic() - t0 < 1.0

    got = registry.get_run(m.run_id)
    assert got.status == "cancelled"
    assert got.result is None and got.resumable is False
    assert "stopped" in (got.error or "")
    assert await asyncio.to_thread(server.client_hung_up.wait, 3)
    assert not server.finished.is_set()
