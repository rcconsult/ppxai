"""`FakeTransport` -- an in-memory `RemoteTransport` for ADR 0013 tests.

Phases 3-5 (session manager, proxy, picker) are written against the S2
Protocol; this double lets them run with no ssh and no network. Every call is
recorded, and outcomes are scripted per call:

    t = FakeTransport()
    t.on_run(["ppxai-server", "--list", "--json"], RunResult(0, "[]", ""))
    t.on_run(["uname"], HostUnreachableError("down", stderr="ssh: connect ..."))
    t.on_forward("/run/user/1000/ppxai/9f2c.sock", LocalEndpoint("tcp", "127.0.0.1:5"))

An unscripted `run` or `forward` raises `AssertionError`, so a test never
silently exercises a path it did not plan.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from ppxai.remote.transport import LocalEndpoint, RemoteTransportError, RunResult

RunOutcome = RunResult | RemoteTransportError | Callable[[list[str]], RunResult]
ForwardOutcome = LocalEndpoint | RemoteTransportError


@dataclass
class FakeTransport:
    runs: dict[tuple[str, ...], list[RunOutcome]] = field(default_factory=dict)
    forwards: dict[str, list[ForwardOutcome]] = field(default_factory=dict)
    run_calls: list[tuple[list[str], float]] = field(default_factory=list)
    forward_calls: list[str] = field(default_factory=list)
    open_forwards: list[LocalEndpoint] = field(default_factory=list)
    closed: int = 0

    def on_run(self, argv: Sequence[str], *outcomes: RunOutcome) -> FakeTransport:
        """Queue outcomes for `argv`; the last one repeats once the queue is spent."""
        self.runs.setdefault(tuple(argv), []).extend(outcomes)
        return self

    def on_forward(self, remote_socket: str, *outcomes: ForwardOutcome) -> FakeTransport:
        self.forwards.setdefault(remote_socket, []).extend(outcomes)
        return self

    @staticmethod
    def _next(queue: list):
        return queue.pop(0) if len(queue) > 1 else queue[0]

    async def run(self, argv: Sequence[str], *, timeout: float) -> RunResult:
        argv = list(argv)
        self.run_calls.append((argv, timeout))
        queue = self.runs.get(tuple(argv))
        if not queue:
            raise AssertionError(f"FakeTransport: unscripted run {argv!r}")
        outcome = self._next(queue)
        if isinstance(outcome, RemoteTransportError):
            raise outcome
        if callable(outcome):
            return outcome(argv)
        return outcome

    async def forward(self, remote_socket: str) -> LocalEndpoint:
        self.forward_calls.append(remote_socket)
        queue = self.forwards.get(remote_socket)
        if not queue:
            raise AssertionError(f"FakeTransport: unscripted forward {remote_socket!r}")
        outcome = self._next(queue)
        if isinstance(outcome, RemoteTransportError):
            raise outcome
        self.open_forwards.append(outcome)
        return outcome

    async def close(self) -> None:
        self.closed += 1
        self.open_forwards.clear()
