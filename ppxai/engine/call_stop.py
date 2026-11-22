"""A stop handle for a blocking provider call running in a worker thread.

A run's model call runs in `asyncio.to_thread`. Cancelling the awaiting task
ends the run, but leaves the thread, and its HTTP request, running: the
tokens are still spent. A provider that can abort its request (it streams,
and closes the stream) registers a closer here; `stop()` runs it from the
event loop's thread, which makes the blocked read in the worker fail, and the
provider then raises `CallAbortedError`.

Leaf module: imports nothing from ppxai, so the run registry and the
providers can both use it.
"""

from __future__ import annotations

import contextvars
import socket
import threading
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any


class CallAbortedError(Exception):
    """The call was stopped through its `CallStop` before it finished."""


class CallStop:
    """Thread-safe: `stop()` is called from the event loop, `on_stop`,
    `remove` and `stopped` from the worker thread making the call."""

    def __init__(self) -> None:
        self._event = threading.Event()
        self._lock = threading.Lock()
        self._closers: list[Callable[[], object]] = []

    @property
    def stopped(self) -> bool:
        return self._event.is_set()

    def on_stop(self, closer: Callable[[], object]) -> None:
        """Run `closer` when the call is stopped, or now if it already was."""
        with self._lock:
            if not self._event.is_set():
                self._closers.append(closer)
                return
        _quietly(closer)

    def remove(self, closer: Callable[[], object]) -> None:
        with self._lock:
            if closer in self._closers:
                self._closers.remove(closer)

    def stop(self) -> None:
        with self._lock:
            if self._event.is_set():
                return
            self._event.set()
            closers, self._closers = self._closers, []
        for closer in closers:
            _quietly(closer)

    def raise_if_stopped(self) -> None:
        if self._event.is_set():
            raise CallAbortedError("the call was stopped")


def _quietly(closer: Callable[[], object]) -> None:
    try:
        closer()
    except Exception:  # noqa: BLE001 — closing an aborted stream may raise; the abort is what matters
        pass


def close_http_stream(stream: object) -> None:
    """Abort an OpenAI SDK `Stream` from another thread (see
    `close_http_response`); `.response` is its httpx `Response`."""
    if close_http_response(getattr(stream, "response", None)):
        return
    close = getattr(stream, "close", None)
    if close is not None:
        _quietly(close)


def close_http_response(response: object) -> bool:
    """Abort a streamed httpx response from another thread, so a read
    blocked on it fails now. Returns True when its socket was found (and
    shut down, or already dead).

    Closing the socket isn't enough: on macOS (and often Linux) a `recv`
    blocked in another thread doesn't wake when its socket is closed.
    Shutting the socket down does, and it is what tells the provider the
    client has gone. Once it is shut down, the socket is NOT also closed
    here: closing it from this thread races the worker's next read (the
    worker can be between `poll` and `recv` on a descriptor that was just
    closed, and block there; seen under load on macOS). The worker's read
    fails on the shut-down socket and the SDK closes it on its own thread.
    A shutdown that fails (the peer already reset it, or it is closed)
    leaves a socket the read fails on anyway: still no close here. Only
    when there is no socket at all is the response closed from this thread.
    Duck-typed (httpx's `network_stream` extension is httpcore's, which
    exposes the socket) so this module imports no SDK.
    """
    if response is None:
        return False
    extensions = getattr(response, "extensions", None) or {}
    network = extensions.get("network_stream") if isinstance(extensions, dict) else None
    sock = None
    if network is not None and hasattr(network, "get_extra_info"):
        try:
            sock = network.get_extra_info("socket")
        except Exception:  # noqa: BLE001 — a transport without a socket
            sock = None
    if sock is not None:
        try:
            sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass  # already reset or shut down: the worker's read fails on it
        return True
    close = getattr(response, "close", None)
    if close is not None:
        _quietly(close)
    return False


# --- for SDKs that don't hand back their response ----------------------------
#
# google-genai's streaming call is a generator that keeps its httpx response
# to itself. The provider passes its own httpx client with
# `event_hooks={"response": [register_response]}`; inside `active(stop)`,
# every response that client receives on this thread can be aborted by
# `stop`. The hook runs on the thread making the call, before the body is
# read, so a thread-local is the right scope.

_active = threading.local()


@contextmanager
def active(stop: CallStop) -> Iterator[None]:
    """Make `stop` able to abort the HTTP responses this thread receives
    through a client hooked with `register_response`."""
    previous = getattr(_active, "frame", None)
    frame: tuple[CallStop, list[Callable[[], object]]] = (stop, [])
    _active.frame = frame
    try:
        yield
    finally:
        _active.frame = previous
        for closer in frame[1]:
            stop.remove(closer)


def register_response(response: object) -> None:
    """httpx `response` event hook: see `active`. A no-op outside it."""
    frame = getattr(_active, "frame", None)
    if frame is None:
        return
    stop, closers = frame
    closer = lambda: close_http_response(response)  # noqa: E731 — removed by identity
    closers.append(closer)
    stop.on_stop(closer)


def refuse_new_requests(client: object) -> None:
    """Make an httpx client refuse any further request, without closing the
    connections a worker thread may still be reading (see
    `close_http_response` for why closing from here is unsafe). The OpenAI
    SDK retries a request whose connection failed; this makes the retry
    fail at once instead of resending the request. Falls back to
    `client.close()` on a client without httpx's `_state`."""
    state = getattr(client, "_state", None)
    closed = getattr(type(state), "CLOSED", None) if state is not None else None
    if closed is not None:
        client._state = closed  # type: ignore[attr-defined]
        return
    close = getattr(client, "close", None)
    if close is not None:
        _quietly(close)


def shutdown_client_connections(client: object) -> int:
    """Shut down the socket of every connection in an httpx client's pool,
    so a request blocked in another thread fails now. Returns how many.

    For a call that hands back nothing to close (a non-streamed request,
    still waiting for its response): only safe on a client nobody else is
    using, such as a `/task` run's own provider. Best effort over httpx's and
    httpcore's internals: anything missing means nothing is shut down, and
    the run still ends; the call just runs to the end in its thread.
    """
    transport = getattr(client, "_transport", None)
    pool = getattr(transport, "_pool", None)
    shut = 0
    for connection in list(getattr(pool, "connections", None) or []):
        inner = getattr(connection, "_connection", None)
        network = getattr(inner, "_network_stream", None)
        if network is None or not hasattr(network, "get_extra_info"):
            continue
        try:
            sock = network.get_extra_info("socket")
        except Exception:  # noqa: BLE001 — a transport without a socket
            continue
        if sock is None:
            continue
        try:
            sock.shutdown(socket.SHUT_RDWR)
            shut += 1
        except OSError:
            pass  # already closed
    return shut


# --- the run's control, for the engine's tool loop --------------------------
#
# A `/task` run drives `EngineClient.chat`; its tool loop makes the provider
# calls. The task runner installs the run's control here (an object with
# `interruptible(call, *, stop=None, resumable=False)`, i.e. RunControl), and
# the loop awaits each provider call through it. Outside a run nothing is
# installed and the loop behaves as before.

_interrupter: contextvars.ContextVar[Any] = contextvars.ContextVar("ppxai_run_interrupter", default=None)


@contextmanager
def install_interrupter(interrupter: Any) -> Iterator[None]:
    token = _interrupter.set(interrupter)
    try:
        yield
    finally:
        _interrupter.reset(token)


def current_interrupter() -> Any:
    return _interrupter.get()
