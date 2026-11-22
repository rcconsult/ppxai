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

import socket
import threading
from collections.abc import Callable


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
    """Close a streamed HTTP response from another thread, so a read blocked
    on it fails now.

    Closing the socket alone isn't enough: on macOS (and often Linux) a
    `recv` blocked in another thread doesn't wake when its socket is closed.
    Shutting the socket down does, and it is what tells the provider the
    client has gone. Duck-typed over the OpenAI SDK's `Stream` (`.response`
    is an httpx `Response`, whose `network_stream` extension is httpcore's,
    which exposes the socket) so this module stays free of SDK imports.
    """
    response = getattr(stream, "response", None)
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
            pass  # already closed
    close = getattr(stream, "close", None)
    if close is not None:
        _quietly(close)
