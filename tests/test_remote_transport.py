"""ADR 0013 Phase 2 -- S2, `RemoteTransport` and `OpenSSHTransport`.

Everything here runs without ssh and without the network: `tests/fake_ssh.py`
stands in for the ssh binary (it runs commands through a real local `sh`, so
the quoting tests are end-to-end), and `tests/remote_fakes.FakeTransport` is
the Protocol double later phases build on. One opt-in test at the bottom
reaches a real host named by `PPXAI_TEST_SSH_DEST`.
"""

from __future__ import annotations

import asyncio
import json
import os
import shlex
import shutil
import socket
import stat
import sys
import tempfile
import threading
from pathlib import Path

import pytest

from ppxai.remote import (
    AuthFailedError,
    ForwardFailedError,
    HostKeyRejectedError,
    HostUnreachableError,
    LocalEndpoint,
    OpenSSHTransport,
    RemoteCommandFailedError,
    RemoteTransport,
    RemoteTransportError,
    RunResult,
    TransportTimeoutError,
    classify_ssh_failure,
    quote_remote_argv,
)
from ppxai.remote.openssh import validate_destination, validate_remote_socket
from tests.remote_fakes import FakeTransport

FAKE_SSH = (sys.executable, str(Path(__file__).with_name("fake_ssh.py")))
posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="needs a POSIX sh and AF_UNIX sockets")


def _transport(**kwargs) -> OpenSSHTransport:
    return OpenSSHTransport("gpu01", ssh_command=FAKE_SSH, **kwargs)


# ---------------------------------------------------------------------------
# The Protocol
# ---------------------------------------------------------------------------

class TestProtocol:
    def test_openssh_transport_satisfies_the_protocol(self):
        assert isinstance(OpenSSHTransport("gpu01"), RemoteTransport)

    def test_the_fake_satisfies_the_protocol(self):
        assert isinstance(FakeTransport(), RemoteTransport)

    def test_every_typed_error_is_a_transport_error(self):
        for cls in (AuthFailedError, ForwardFailedError, HostKeyRejectedError, HostUnreachableError,
                    RemoteCommandFailedError, TransportTimeoutError):
            assert issubclass(cls, RemoteTransportError)

    def test_an_error_keeps_the_stderr_verbatim(self):
        err = AuthFailedError("ssh authentication failed", stderr="Permission denied (publickey).\n", rc=255)
        assert err.stderr == "Permission denied (publickey).\n"
        assert err.rc == 255
        assert "Permission denied (publickey)." in str(err)

    def test_check_passes_a_zero_exit_through(self):
        r = RunResult(0, "ok", "")
        assert r.check() is r

    def test_check_raises_on_a_non_zero_exit(self):
        with pytest.raises(RemoteCommandFailedError) as exc:
            RunResult(3, "", "boom\n").check(["ppxai-server", "--list"])
        assert exc.value.rc == 3
        assert exc.value.stderr == "boom\n"
        assert "ppxai-server --list" in str(exc.value)


# ---------------------------------------------------------------------------
# Quoting -- the one site where argv becomes a shell string
# ---------------------------------------------------------------------------

QUOTING_CASES = [
    ["ppxai-server", "--list", "--json"],
    ["echo", "two words"],
    ["echo", "it's"],
    ["echo", 'say "hi"'],
    ["echo", "$HOME"],
    ["echo", "$(id -u)"],
    ["echo", "`id -u`"],
    ["echo", "a; rm -rf /tmp/nope && false | true"],
    ["echo", "*"],
    ["echo", ""],
    ["echo", "-n"],
    ["echo", "tab\there"],
    ["echo", "\\backslash\\"],
    ["echo", "ünïcødé ✓"],
    ["echo", "'\"'\"'"],
]


class TestQuoting:
    @posix_only
    @pytest.mark.parametrize("argv", QUOTING_CASES, ids=range(len(QUOTING_CASES)))
    def test_a_real_sh_gets_back_exactly_the_argv(self, argv):
        # printf '%s\0' prints each argument NUL-terminated: splitting on NUL
        # recovers what the shell actually parsed, argument by argument.
        # The format is itself an argv element, so it is quoted like the rest.
        probe = ["printf", "%s\\0", *argv]
        out = asyncio.run(_transport().run(probe, timeout=10))
        assert out.rc == 0, out.stderr
        assert out.stdout.split("\0")[:-1] == argv

    @pytest.mark.parametrize("bad", ["a\nb", "a\rb", "a\x00b"])
    def test_line_breaks_and_nul_are_refused(self, bad):
        with pytest.raises(ValueError):
            quote_remote_argv(["echo", bad])

    def test_an_empty_argv_is_refused(self):
        with pytest.raises(ValueError):
            quote_remote_argv([])

    def test_a_non_string_element_is_refused(self):
        with pytest.raises(TypeError):
            quote_remote_argv(["echo", 3])

    def test_the_command_is_one_argument_after_the_destination(self):
        argv = _transport().run_argv(["echo", "a b"])
        assert argv[-2] == "gpu01"
        assert argv[-1] == "echo 'a b'"


# ---------------------------------------------------------------------------
# OpenSSH stderr -> typed errors
# ---------------------------------------------------------------------------

# Real OpenSSH wording (8.x/9.x; macOS, Linux, Windows builds).
CLASSIFY_CASES = [
    ("ssh: Could not resolve hostname nosuch: nodename nor servname provided, or not known\r\n", HostUnreachableError),
    ("ssh: Could not resolve hostname nosuch: Name or service not known\n", HostUnreachableError),
    ("ssh: connect to host 10.0.0.9 port 22: Connection refused\n", HostUnreachableError),
    ("ssh: connect to host 10.0.0.9 port 22: Operation timed out\n", HostUnreachableError),
    ("ssh: connect to host 10.0.0.9 port 22: Connection timed out\n", HostUnreachableError),
    ("ssh: connect to host 10.0.0.9 port 22: No route to host\n", HostUnreachableError),
    ("ssh: connect to host 10.0.0.9 port 22: Network is unreachable\n", HostUnreachableError),
    ("kex_exchange_identification: Connection closed by remote host\n", HostUnreachableError),
    ("Connection closed by 10.0.0.9 port 22\n", HostUnreachableError),
    ("Connection reset by 10.0.0.9 port 22\n", HostUnreachableError),
    ("user@gpu01: Permission denied (publickey).\n", AuthFailedError),
    ("user@gpu01: Permission denied (publickey,password,keyboard-interactive).\n", AuthFailedError),
    ("Received disconnect from 10.0.0.9 port 22:2: Too many authentication failures\n", AuthFailedError),
    ("No ED25519 host key is known for gpu01 and you have requested strict checking.\n"
     "Host key verification failed.\n", HostKeyRejectedError),
    ("@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
     "@    WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!     @\n"
     "@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@@\n"
     "Host key verification failed.\n", HostKeyRejectedError),
    ("bind [127.0.0.1]:53811: Address already in use\n"
     "channel_setup_fwd_listener_tcpip: cannot listen to port: 53811\n"
     "Could not request local forwarding.\n", ForwardFailedError),
    ("unix_listener: cannot bind to path /tmp/x/s.sock: Permission denied\n"
     "Could not request local forwarding.\n", ForwardFailedError),
    ("Bad local forwarding specification 'x'\n", ForwardFailedError),
]


class TestClassify:
    @pytest.mark.parametrize("stderr,expected", CLASSIFY_CASES,
                             ids=[c[1].__name__ + f"-{i}" for i, c in enumerate(CLASSIFY_CASES)])
    def test_openssh_messages_map_to_the_right_type(self, stderr, expected):
        err = classify_ssh_failure(stderr, rc=255)
        assert type(err) is expected
        assert err.stderr == stderr
        assert err.rc == 255

    def test_a_host_key_failure_is_never_read_as_an_auth_failure(self):
        # A changed-key banner can precede other noise; the host key wins.
        stderr = ("WARNING: REMOTE HOST IDENTIFICATION HAS CHANGED!\n"
                  "Permission denied (publickey).\n")
        assert type(classify_ssh_failure(stderr, rc=255)) is HostKeyRejectedError

    def test_a_unix_listener_permission_error_is_a_forward_failure_not_auth(self):
        # Its text contains "Permission denied" but not "Permission denied (".
        stderr = "unix_listener: cannot bind to path /x: Permission denied\n"
        assert type(classify_ssh_failure(stderr, rc=255)) is ForwardFailedError

    def test_unrecognised_text_is_not_an_ssh_failure(self):
        assert classify_ssh_failure("some tool printed this\n", rc=255) is None

    def test_unrecognised_text_is_a_forward_failure_when_forwarding(self):
        err = classify_ssh_failure("mystery\n", rc=1, forwarding=True)
        assert type(err) is ForwardFailedError
        assert err.stderr == "mystery\n"


# ---------------------------------------------------------------------------
# Input validation -- nothing reaches ssh's option parser
# ---------------------------------------------------------------------------

class TestValidation:
    @pytest.mark.parametrize("good", ["gpu01", "user@gpu01", "host.example.com",
                                      "ssh://user@host:2222", "lab-mac"])
    def test_ordinary_destinations_pass(self, good):
        assert validate_destination(good) == good

    @pytest.mark.parametrize("bad", ["", "-oProxyCommand=touch /tmp/pwned",
                                     "-p", "two words", "tab\there", "line\nbreak"])
    def test_option_injection_and_whitespace_are_refused(self, bad):
        with pytest.raises(ValueError):
            validate_destination(bad)

    def test_the_constructor_validates(self):
        with pytest.raises(ValueError):
            OpenSSHTransport("-oProxyCommand=x")

    @pytest.mark.parametrize("good", ["/run/user/1000/ppxai/9f2c.sock",
                                      "/home/u/.ppxai/run/sock/9f2c.sock"])
    def test_absolute_socket_paths_pass(self, good):
        assert validate_remote_socket(good) == good

    @pytest.mark.parametrize("bad", ["relative.sock", "~/.ppxai/s.sock",
                                     "/a:b.sock", "/with space.sock", "/nul\x00.sock", ""])
    def test_other_socket_paths_are_refused(self, bad):
        with pytest.raises(ValueError):
            validate_remote_socket(bad)


# ---------------------------------------------------------------------------
# The argv OpenSSHTransport hands ssh
# ---------------------------------------------------------------------------

class TestArgv:
    def test_run_never_prompts_and_never_allocates_a_tty(self):
        argv = OpenSSHTransport("gpu01").run_argv(["true"])
        assert argv[0] == "ssh"
        assert argv[argv.index("-o") + 1] == "BatchMode=yes"
        assert "ConnectTimeout=10" in argv
        assert "-T" in argv

    def test_a_uds_forward_is_private_and_fails_fast(self):
        t = OpenSSHTransport("gpu01")
        argv = t.forward_argv(LocalEndpoint("uds", "/tmp/d/s.sock"), "/run/user/1/p/x.sock")
        assert "BatchMode=yes" in argv
        assert "ExitOnForwardFailure=yes" in argv
        assert "StreamLocalBindMask=0177" in argv
        assert "-N" in argv
        assert argv[argv.index("-L") + 1] == "/tmp/d/s.sock:/run/user/1/p/x.sock"
        assert argv[-1] == "gpu01"

    def test_a_tcp_forward_binds_loopback_only(self):
        t = OpenSSHTransport("gpu01")
        argv = t.forward_argv(LocalEndpoint("tcp", "127.0.0.1:5555"), "/r/x.sock")
        assert argv[argv.index("-L") + 1] == "127.0.0.1:5555:/r/x.sock"

    def test_the_forward_argv_validates_the_remote_socket(self):
        with pytest.raises(ValueError):
            OpenSSHTransport("gpu01").forward_argv(
                LocalEndpoint("tcp", "127.0.0.1:1"), "/a:b")

    def test_windows_defaults_to_a_tcp_forward(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "win32")
        assert OpenSSHTransport("gpu01")._local_kind == "tcp"

    def test_posix_defaults_to_a_uds_forward(self, monkeypatch):
        monkeypatch.setattr(sys, "platform", "linux")
        assert OpenSSHTransport("gpu01")._local_kind == "uds"


# ---------------------------------------------------------------------------
# run() through the fake ssh binary
# ---------------------------------------------------------------------------

class TestRun:
    @posix_only
    async def test_stdout_stderr_and_status_come_back(self):
        r = await _transport().run(["sh", "-c", "echo out; echo err >&2; exit 3"], timeout=10)
        assert (r.rc, r.stdout, r.stderr) == (3, "out\n", "err\n")

    @posix_only
    async def test_a_remote_255_with_no_ssh_message_is_the_commands_own(self):
        r = await _transport().run(["sh", "-c", "echo mine >&2; exit 255"], timeout=10)
        assert r.rc == 255
        assert r.stderr == "mine\n"

    @pytest.mark.parametrize("stderr,expected", [
        ("user@gpu01: Permission denied (publickey).\r\n", AuthFailedError),
        ("Host key verification failed.\r\n", HostKeyRejectedError),
        ("ssh: Could not resolve hostname gpu01: Name or service not known\r\n", HostUnreachableError),
    ])
    async def test_ssh_failures_raise_typed_errors(self, monkeypatch, stderr, expected):
        monkeypatch.setenv("FAKE_SSH_RC", "255")
        monkeypatch.setenv("FAKE_SSH_STDERR", stderr)
        with pytest.raises(expected) as exc:
            await _transport().run(["true"], timeout=10)
        assert exc.value.stderr == stderr

    async def test_a_hung_ssh_is_killed_at_the_timeout(self, monkeypatch):
        monkeypatch.setenv("FAKE_SSH_SLEEP", "30")
        with pytest.raises(TransportTimeoutError):
            await _transport().run(["true"], timeout=0.5)

    async def test_the_real_argv_reaches_the_binary(self, monkeypatch, tmp_path):
        log = tmp_path / "argv.jsonl"
        monkeypatch.setenv("FAKE_SSH_ARGV_LOG", str(log))
        monkeypatch.setenv("FAKE_SSH_RC", "0")
        await _transport().run(["ppxai-server", "--list", "--json"], timeout=10)
        seen = json.loads(log.read_text().splitlines()[0])
        assert seen[-2:] == ["gpu01", "ppxai-server --list --json"]
        assert "BatchMode=yes" in seen


# ---------------------------------------------------------------------------
# forward() through the fake ssh binary
# ---------------------------------------------------------------------------

class _EchoServer:
    """A unix-socket server standing in for the remote ppxai-server."""

    def __init__(self):
        # Short path: sun_path is 104 bytes on macOS and tmp_path is long.
        self.dir = tempfile.mkdtemp(prefix="ppx-", dir="/tmp")
        self.path = os.path.join(self.dir, "r.sock")
        self.sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self.sock.bind(self.path)
        self.sock.listen(8)
        threading.Thread(target=self._serve, daemon=True).start()

    def _serve(self):
        while True:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            # The forward's readiness probe connects and closes at once, so the
            # first connection is often already shut down. Linux raises EPIPE
            # on the reply (macOS does not); it must not kill the server.
            try:
                with conn:
                    data = conn.recv(1024)
                    if data:
                        conn.sendall(b"echo:" + data)
            except OSError:
                continue

    def close(self):
        self.sock.close()
        shutil.rmtree(self.dir, ignore_errors=True)


@pytest.fixture
def remote_server():
    server = _EchoServer()
    yield server
    server.close()


async def _roundtrip(endpoint: LocalEndpoint, payload: bytes) -> bytes:
    if endpoint.kind == "uds":
        reader, writer = await asyncio.open_unix_connection(endpoint.address)
    else:
        host, port = endpoint.address.rsplit(":", 1)
        reader, writer = await asyncio.open_connection(host, int(port))
    writer.write(payload)
    await writer.drain()
    data = await asyncio.wait_for(reader.read(1024), timeout=5)
    writer.close()
    return data


@posix_only
class TestForward:
    async def test_a_uds_forward_relays_bytes_and_is_private(self, remote_server):
        t = _transport()
        try:
            ep = await t.forward(remote_server.path)
            assert ep.kind == "uds"
            parent = Path(ep.address).parent
            assert stat.S_IMODE(parent.stat().st_mode) == 0o700
            assert await _roundtrip(ep, b"ping") == b"echo:ping"
        finally:
            await t.close()
        assert not parent.exists(), "close() must remove the private directory"

    async def test_a_tcp_forward_relays_bytes(self, remote_server):
        t = _transport(local_forward_kind="tcp")
        try:
            ep = await t.forward(remote_server.path)
            assert ep.kind == "tcp"
            assert ep.address.startswith("127.0.0.1:")
            assert await _roundtrip(ep, b"ping") == b"echo:ping"
        finally:
            await t.close()

    async def test_close_stops_every_forward_and_is_idempotent(self, remote_server):
        t = _transport()
        await t.forward(remote_server.path)
        await t.forward(remote_server.path)
        procs = [f.process for f in t._forwards]
        await t.close()
        assert all(p.returncode is not None for p in procs)
        await t.close()

    async def test_a_forward_ssh_refuses_is_a_forward_failed(self, monkeypatch):
        stderr = ("bind [127.0.0.1]:1: Address already in use\n"
                  "Could not request local forwarding.\n")
        monkeypatch.setenv("FAKE_SSH_RC", "255")
        monkeypatch.setenv("FAKE_SSH_STDERR", stderr)
        t = _transport()
        with pytest.raises(ForwardFailedError) as exc:
            await t.forward("/run/user/1/p/x.sock")
        assert "Address already in use" in exc.value.stderr
        assert t._forwards == []

    async def test_an_auth_failure_during_a_forward_keeps_its_type(self, monkeypatch):
        monkeypatch.setenv("FAKE_SSH_RC", "255")
        monkeypatch.setenv("FAKE_SSH_STDERR", "u@gpu01: Permission denied (publickey).\n")
        with pytest.raises(AuthFailedError):
            await _transport().forward("/run/user/1/p/x.sock")

    async def test_the_private_dir_is_removed_when_the_forward_fails(self, monkeypatch):
        monkeypatch.setenv("FAKE_SSH_RC", "255")
        monkeypatch.setenv("FAKE_SSH_STDERR", "mystery\n")
        before = set(Path(tempfile.gettempdir()).glob("ppxai-fwd-*"))
        with pytest.raises(ForwardFailedError):
            await _transport().forward("/run/user/1/p/x.sock")
        assert set(Path(tempfile.gettempdir()).glob("ppxai-fwd-*")) == before

    async def test_a_forward_that_never_listens_times_out_and_is_killed(self, monkeypatch):
        monkeypatch.setenv("FAKE_SSH_NO_LISTEN", "1")
        t = _transport(forward_ready_timeout_s=0.5)
        with pytest.raises(TransportTimeoutError):
            await t.forward("/run/user/1/p/x.sock")
        assert t._forwards == []

    async def test_a_missing_remote_socket_is_not_the_transports_business(self):
        # Real ssh accepts locally and logs the failed channel; liveness is
        # the session manager's /health check (S4), not the forward's.
        t = _transport()
        try:
            ep = await t.forward("/nonexistent/x.sock")
            assert ep.kind == "uds"
        finally:
            await t.close()


# ---------------------------------------------------------------------------
# FakeTransport -- the double later phases use
# ---------------------------------------------------------------------------

class TestFakeTransport:
    async def test_scripted_outcomes_play_in_order_and_the_last_repeats(self):
        t = FakeTransport().on_run(
            ["uname"], HostUnreachableError("down"), RunResult(0, "Linux\n", ""))
        with pytest.raises(HostUnreachableError):
            await t.run(["uname"], timeout=5)
        assert (await t.run(["uname"], timeout=5)).stdout == "Linux\n"
        assert (await t.run(["uname"], timeout=5)).stdout == "Linux\n"
        assert [c[0] for c in t.run_calls] == [["uname"]] * 3

    async def test_an_unscripted_call_fails_loudly(self):
        with pytest.raises(AssertionError):
            await FakeTransport().run(["ls"], timeout=5)
        with pytest.raises(AssertionError):
            await FakeTransport().forward("/x.sock")

    async def test_forward_and_close_are_recorded(self):
        ep = LocalEndpoint("tcp", "127.0.0.1:1")
        t = FakeTransport().on_forward("/x.sock", ep)
        assert await t.forward("/x.sock") == ep
        assert t.open_forwards == [ep]
        await t.close()
        assert t.closed == 1 and t.open_forwards == []


# ---------------------------------------------------------------------------
# Opt-in: a real host
# ---------------------------------------------------------------------------

LIVE_DEST = os.environ.get("PPXAI_TEST_SSH_DEST", "")
# Optional ssh argv prefix, e.g. `ssh -o UserKnownHostsFile=/path/known_hosts`
# for a test sshd whose key is not in the user's own known_hosts.
LIVE_SSH = tuple(shlex.split(os.environ.get("PPXAI_TEST_SSH_COMMAND", "ssh"), posix=sys.platform != "win32"))


@pytest.mark.network
@pytest.mark.skipif(not LIVE_DEST, reason="set PPXAI_TEST_SSH_DEST to an ssh destination")
class TestLive:
    async def test_run_reaches_the_host(self):
        r = await OpenSSHTransport(LIVE_DEST, ssh_command=LIVE_SSH).run(["uname", "-s"], timeout=30)
        assert r.rc == 0 and r.stdout.strip()

    async def test_an_unknown_host_is_unreachable(self):
        with pytest.raises(HostUnreachableError):
            await OpenSSHTransport("nosuchhost.invalid", ssh_command=LIVE_SSH).run(["true"], timeout=30)
