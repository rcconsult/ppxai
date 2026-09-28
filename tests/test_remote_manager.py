"""ADR 0013 Phase 3 -- S1 inventory, the hub's contract record, and S4's
`RemoteSessionManager`.

Most tests drive the manager through `FakeTransport` and a scripted HTTP
requester, so every state transition is exercised with no ssh and no
network. Two classes go further: the remote shell snippets run through a real
`sh` (via `tests/fake_ssh.py`), and one slow end-to-end test launches a real
`ppxai-server --uds --announce --detach` through the fake ssh, attaches over a
real forward, health-checks it with the real HTTP client, and stops it.
"""

from __future__ import annotations

import asyncio
import json
import os
import shutil
import stat
import sys
import tempfile
import time
from pathlib import Path, PurePosixPath

import pytest

from ppxai.remote import (
    KNOWN_CONTRACTS,
    MIN_SERVER_VERSION,
    ForwardFailedError,
    HostUnreachableError,
    InventoryError,
    LocalEndpoint,
    MalformedEntryError,
    OpenSSHTransport,
    RemoteCommandFailedError,
    RemoteHost,
    RemoteSessionManager,
    RunResult,
    ServerNotInstalledError,
    State,
    UnknownContractError,
    UnknownHostError,
    UnknownServerError,
    UnsupportedServerError,
    parse_hosts,
)
from ppxai.remote.contract import parse_entry, version_tuple
from ppxai.remote.manager import (
    _CD_EXEC_SCRIPT,
    _DEFAULT_CANDIDATES,
    _DISCOVER_SCRIPT,
    ALLOWED_TRANSITIONS,
)
from ppxai.server import registry
from ppxai.version import __version__
from tests.remote_fakes import FakeTransport

FAKE_SSH = (sys.executable, str(Path(__file__).with_name("fake_ssh.py")))
posix_only = pytest.mark.skipif(
    sys.platform == "win32", reason="needs a POSIX sh and AF_UNIX sockets")

BIN = "/home/u/.local/bin/ppxai-server"
SID = "9f2c0000aaaa1111"
SOCK = "/run/user/1000/ppxai/9f2c0000aaaa1111.sock"
DISCOVER = ["sh", "-c", _DISCOVER_SCRIPT, "sh", *_DEFAULT_CANDIDATES]
LIST = [BIN, "--list", "--json"]
EP = LocalEndpoint("tcp", "127.0.0.1:50001")


def entry(sid=SID, **overrides):
    base = {
        "contract": 1, "id": sid, "pid": 4242, "socket": SOCK if sid == SID else f"/run/{sid}.sock",
        "token": "tok-" + sid, "version": "1.19.4", "app_state_schema": "1.1",
        "workdir": "/home/u/src", "started_at": "2026-09-28T10:00:00Z", "label": None,
    }
    base.update(overrides)
    return base


class Rig:
    """A manager wired to fakes, recording events and HTTP calls."""

    def __init__(self, hosts=None):
        self.runs: dict = {}
        self.forwards: dict = {}
        self.made: list[FakeTransport] = []
        self.status: dict = {}
        self.http_calls: list = []
        self.events: list = []
        self.now = 0.0
        self.mgr = RemoteSessionManager(
            hosts or [RemoteHost("gpu01", "gpu01")],
            transport_factory=self._factory, http=self._http,
            clock=lambda: self.now, retry_base_s=1, retry_max_s=8)
        self.mgr.subscribe(self.events.append)
        self.on_run(DISCOVER, RunResult(0, BIN + "\n", ""))

    def _factory(self, host):
        t = FakeTransport(runs=self.runs, forwards=self.forwards)
        self.made.append(t)
        return t

    async def _http(self, endpoint, token, method, path):
        self.http_calls.append((endpoint, token, method, path))
        queue = self.status.get((method, path), [200])
        return queue.pop(0) if len(queue) > 1 else queue[0]

    def on_run(self, argv, *outcomes):
        self.runs.setdefault(tuple(argv), []).extend(outcomes)

    def listing(self, *entries):
        self.runs[tuple(LIST)] = [RunResult(0, json.dumps(list(entries)), "")]

    def health(self, *codes):
        self.status[("GET", "/health")] = list(codes)

    def states(self):
        return [e.state for e in self.events]


# ---------------------------------------------------------------------------
# S1 -- inventory
# ---------------------------------------------------------------------------

class TestInventory:
    def test_no_remote_block_means_no_hosts(self):
        assert parse_hosts(None) == []
        assert parse_hosts({}) == []

    def test_hosts_parse_in_order(self):
        hosts = parse_hosts({"hosts": [
            {"id": "gpu01", "ssh": "gpu01"},
            {"id": "lab-mac", "ssh": "u@lab-mac", "ppxai_server": "~/.local/bin/ppxai-server"},
        ]})
        assert hosts == [RemoteHost("gpu01", "gpu01"),
                         RemoteHost("lab-mac", "u@lab-mac", "~/.local/bin/ppxai-server")]

    @pytest.mark.parametrize("bad_id", ["GPU", "a/b", "..", "", "x" * 33, "a b", 7, None])
    def test_an_id_that_is_not_a_safe_path_segment_is_refused(self, bad_id):
        with pytest.raises(InventoryError, match="id"):
            parse_hosts({"hosts": [{"id": bad_id, "ssh": "h"}]})

    def test_local_is_reserved_for_the_hub_itself(self):
        with pytest.raises(InventoryError, match="reserved"):
            parse_hosts({"hosts": [{"id": "local", "ssh": "h"}]})

    def test_duplicate_ids_are_refused(self):
        with pytest.raises(InventoryError, match="duplicate"):
            parse_hosts({"hosts": [{"id": "a", "ssh": "h"}, {"id": "a", "ssh": "g"}]})

    @pytest.mark.parametrize("ssh", ["-oProxyCommand=x", "two words", "", None])
    def test_an_ssh_value_that_is_not_one_destination_is_refused(self, ssh):
        with pytest.raises(InventoryError, match="ssh"):
            parse_hosts({"hosts": [{"id": "a", "ssh": ssh}]})

    def test_unknown_keys_are_refused_not_ignored(self):
        with pytest.raises(InventoryError, match="identity_file"):
            parse_hosts({"hosts": [{"id": "a", "ssh": "h", "identity_file": "~/.ssh/k"}]})

    @pytest.mark.parametrize("remote", [[], "x", {"hosts": {}}, {"hosts": ["a"]}])
    def test_wrong_shapes_are_refused(self, remote):
        with pytest.raises(InventoryError):
            parse_hosts(remote)


# ---------------------------------------------------------------------------
# The hub's own record of the S3 contract
# ---------------------------------------------------------------------------

class TestContract:
    def test_the_hub_knows_the_contract_this_server_writes(self):
        assert KNOWN_CONTRACTS[registry.CONTRACT] == registry.ENTRY_FIELDS, (
            "ppxai/server/registry.py changed the entry; bump its CONTRACT and "
            "teach ppxai/remote/contract.py the new one (keep the old one too)")

    def test_a_real_server_entry_parses(self, tmp_path):
        # PurePosixPath: the remote is POSIX even when the test runs on Windows.
        raw = registry.build_entry(server_id=SID, socket_path=PurePosixPath(SOCK),
                                   token="t", workdir=str(tmp_path), label="lab")
        server = parse_entry("gpu01", raw)
        assert (server.id, server.token, server.label) == (SID, "t", "lab")

    def test_the_minimum_version_is_not_newer_than_this_release(self):
        assert version_tuple(MIN_SERVER_VERSION) <= version_tuple(__version__)

    def test_an_unknown_contract_names_both_numbers(self):
        with pytest.raises(UnknownContractError) as exc:
            parse_entry("gpu01", entry(contract=2))
        assert "contract 2" in str(exc.value) and "contract 1" in str(exc.value)

    @pytest.mark.parametrize("change", [
        {"id": "../etc"}, {"pid": "1"}, {"pid": True}, {"socket": "rel.sock"},
        {"token": None},
    ])
    def test_a_malformed_entry_is_refused(self, change):
        with pytest.raises(MalformedEntryError):
            parse_entry("gpu01", entry(**change))

    def test_a_windows_socket_path_is_refused_as_a_non_posix_host(self):
        with pytest.raises(MalformedEntryError, match="POSIX"):
            parse_entry("gpu01", entry(socket=r"C:\Users\u\.ppxai\run\sock\x.sock"))

    def test_a_missing_field_is_refused(self):
        raw = entry()
        del raw["workdir"]
        with pytest.raises(MalformedEntryError, match="workdir"):
            parse_entry("gpu01", raw)

    def test_the_public_shape_and_repr_never_carry_the_token(self):
        server = parse_entry("gpu01", entry())
        assert "token" not in server.public()
        assert "tok-" not in repr(server)


# ---------------------------------------------------------------------------
# The state machine table
# ---------------------------------------------------------------------------

class TestTransitionTable:
    def test_every_state_has_a_row(self):
        assert set(ALLOWED_TRANSITIONS) == set(State)

    def test_gone_is_terminal(self):
        assert ALLOWED_TRANSITIONS[State.GONE] == frozenset()

    def test_every_live_state_can_be_closed(self):
        for state in (State.CONNECTING, State.TUNNELED, State.HEALTHY, State.DEGRADED):
            assert State.DISCONNECTED in ALLOWED_TRANSITIONS[state]

    def test_the_adr_path_to_healthy_exists(self):
        path = [State.DISCONNECTED, State.CONNECTING, State.TUNNELED, State.HEALTHY]
        assert all(b in ALLOWED_TRANSITIONS[a] for a, b in zip(path, path[1:]))


# ---------------------------------------------------------------------------
# servers() and launch()
# ---------------------------------------------------------------------------

class TestServers:
    async def test_lists_readable_entries(self):
        rig = Rig()
        rig.listing(entry(), entry("b" * 16))
        listing = await rig.mgr.servers("gpu01")
        assert [s.id for s in listing.servers] == [SID, "b" * 16]
        assert listing.refused == []

    async def test_an_unknown_contract_is_refused_without_hiding_the_rest(self):
        rig = Rig()
        rig.listing(entry(), entry("c" * 16, contract=9))
        listing = await rig.mgr.servers("gpu01")
        assert [s.id for s in listing.servers] == [SID]
        assert len(listing.refused) == 1 and "contract 9" in listing.refused[0]

    async def test_an_unknown_host_is_refused_before_any_ssh(self):
        rig = Rig()
        with pytest.raises(UnknownHostError):
            await rig.mgr.servers("nope")
        assert rig.made == []

    async def test_the_binary_is_discovered_once_per_host(self):
        rig = Rig()
        rig.listing()
        await rig.mgr.servers("gpu01")
        await rig.mgr.servers("gpu01")
        runs = [argv for t in rig.made for argv, _ in t.run_calls]
        assert runs.count(DISCOVER) == 1

    async def test_a_configured_binary_is_the_only_candidate(self):
        rig = Rig([RemoteHost("gpu01", "gpu01", "~/opt/ppxai-server")])
        rig.on_run(["sh", "-c", _DISCOVER_SCRIPT, "sh", "~/opt/ppxai-server"],
                   RunResult(0, "/home/u/opt/ppxai-server\n", ""))
        rig.on_run(["/home/u/opt/ppxai-server", "--list", "--json"], RunResult(0, "[]", ""))
        assert (await rig.mgr.servers("gpu01")).servers == []

    async def test_no_binary_is_a_clear_refusal(self):
        rig = Rig()
        rig.runs[tuple(DISCOVER)] = [RunResult(127, "", "")]
        with pytest.raises(ServerNotInstalledError, match="ppxai-server not found"):
            await rig.mgr.servers("gpu01")

    async def test_an_old_server_is_refused_naming_its_version(self):
        rig = Rig()
        rig.on_run(LIST, RunResult(2, "", "ppxai-server: error: unrecognized arguments: --list --json\n"))
        rig.on_run([BIN, "--version"], RunResult(0, "ppxai-server 1.19.2\n", ""))
        with pytest.raises(UnsupportedServerError) as exc:
            await rig.mgr.servers("gpu01")
        assert "1.19.2" in str(exc.value) and MIN_SERVER_VERSION in str(exc.value)

    async def test_any_other_failure_is_a_command_failure(self):
        rig = Rig()
        rig.on_run(LIST, RunResult(1, "", "Traceback ...\n"))
        with pytest.raises(RemoteCommandFailedError):
            await rig.mgr.servers("gpu01")

    async def test_non_json_output_is_refused(self):
        rig = Rig()
        rig.on_run(LIST, RunResult(0, "No announced ppxai servers are running.\n", ""))
        with pytest.raises(MalformedEntryError):
            await rig.mgr.servers("gpu01")

    async def test_a_transport_failure_is_recorded_on_the_host(self):
        rig = Rig()
        rig.runs[tuple(DISCOVER)] = [HostUnreachableError("down", stderr="ssh: connect ... refused")]
        with pytest.raises(HostUnreachableError):
            await rig.mgr.servers("gpu01")
        assert "refused" in rig.mgr.hosts()[0]["error"]


class TestLaunch:
    LAUNCH = [BIN, "--uds", "--announce", "--detach"]

    async def test_launch_returns_the_printed_entry(self):
        rig = Rig()
        rig.on_run(self.LAUNCH, RunResult(0, json.dumps(entry()), ""))
        server = await rig.mgr.launch("gpu01")
        assert server.id == SID

    async def test_a_workdir_and_label_go_through_one_quoted_argv(self):
        rig = Rig()
        argv = ["sh", "-c", _CD_EXEC_SCRIPT, "sh", "~/src/my project",
                *self.LAUNCH, "--label", "it's mine"]
        rig.on_run(argv, RunResult(0, json.dumps(entry(label="it's mine")), ""))
        server = await rig.mgr.launch("gpu01", workdir="~/src/my project", label="it's mine")
        assert server.label == "it's mine"

    async def test_the_servers_own_error_is_surfaced(self):
        rig = Rig()
        rig.on_run(self.LAUNCH, RunResult(1, json.dumps({"error": "a server is already listening"}), ""))
        with pytest.raises(RemoteCommandFailedError, match="already listening"):
            await rig.mgr.launch("gpu01")

    async def test_an_old_server_is_refused(self):
        rig = Rig()
        rig.on_run(self.LAUNCH, RunResult(2, "", "error: unrecognized arguments: --uds --announce --detach\n"))
        rig.on_run([BIN, "--version"], RunResult(0, "ppxai-server 1.18.8\n", ""))
        with pytest.raises(UnsupportedServerError, match="1.18.8"):
            await rig.mgr.launch("gpu01")


# ---------------------------------------------------------------------------
# attach / detach / stop and the state machine
# ---------------------------------------------------------------------------

class TestAttach:
    async def test_attach_walks_the_adr_path_to_healthy(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        view = await rig.mgr.attach("gpu01", SID)
        assert view["state"] == "healthy"
        assert rig.states() == [State.CONNECTING, State.TUNNELED, State.HEALTHY]
        assert rig.mgr.route("gpu01", SID) == (EP, "tok-" + SID)

    async def test_health_is_checked_with_the_entrys_token(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        await rig.mgr.attach("gpu01", SID)
        assert rig.http_calls == [(EP, "tok-" + SID, "GET", "/health")]

    async def test_no_public_shape_carries_the_token(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        view = await rig.mgr.attach("gpu01", SID)
        assert "tok-" not in json.dumps(view)
        assert "tok-" not in json.dumps(rig.mgr.hosts())

    async def test_reattaching_is_a_no_op(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        await rig.mgr.attach("gpu01", SID)
        await rig.mgr.attach("gpu01", SID)
        assert sum(len(t.forward_calls) for t in rig.made) == 1

    async def test_an_unknown_server_is_refused(self):
        rig = Rig()
        rig.listing(entry())
        with pytest.raises(UnknownServerError):
            await rig.mgr.attach("gpu01", "f" * 16)

    async def test_a_failed_forward_leaves_nothing_behind(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [ForwardFailedError("no", stderr="Could not request local forwarding.")]
        with pytest.raises(ForwardFailedError):
            await rig.mgr.attach("gpu01", SID)
        assert rig.states() == [State.CONNECTING, State.DISCONNECTED]
        assert rig.mgr.attachment("gpu01", SID) is None
        assert rig.made[-1].closed == 1

    async def test_a_failed_health_check_keeps_it_degraded_not_routable(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        rig.health(401)
        view = await rig.mgr.attach("gpu01", SID)
        assert view["state"] == "degraded" and "401" in view["detail"]
        assert rig.mgr.route("gpu01", SID) is None

    async def test_detach_drops_the_forward_and_never_stops_the_server(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        await rig.mgr.attach("gpu01", SID)
        forward_transport = rig.made[-1]
        await rig.mgr.detach("gpu01", SID)
        assert forward_transport.closed == 1
        assert rig.states()[-1] is State.DISCONNECTED
        assert not any(path == "/shutdown" for *_, path in rig.http_calls)
        assert rig.mgr.attachment("gpu01", SID) is None

    async def test_stop_asks_the_server_itself(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        await rig.mgr.stop("gpu01", SID)
        assert rig.http_calls[-1] == (EP, "tok-" + SID, "POST", "/shutdown")
        assert rig.states()[-1] is State.GONE
        assert rig.mgr.attachment("gpu01", SID) is None

    async def test_a_refused_shutdown_is_an_error_and_keeps_the_attachment(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        rig.status[("POST", "/shutdown")] = [500]
        with pytest.raises(RemoteCommandFailedError, match="500"):
            await rig.mgr.stop("gpu01", SID)
        assert rig.mgr.attachment("gpu01", SID)["state"] == "healthy"

    async def test_a_broken_listener_does_not_break_the_hub(self):
        rig = Rig()
        rig.mgr.subscribe(lambda change: 1 / 0)
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        assert (await rig.mgr.attach("gpu01", SID))["state"] == "healthy"


class TestMonitor:
    async def _healthy(self):
        rig = Rig()
        rig.listing(entry())
        rig.forwards[SOCK] = [EP]
        await rig.mgr.attach("gpu01", SID)
        rig.events.clear()
        return rig

    async def test_a_failed_probe_degrades(self):
        rig = await self._healthy()
        rig.health(0)
        await rig.mgr.tick()
        assert rig.states() == [State.DEGRADED]
        assert rig.mgr.route("gpu01", SID) is None

    async def test_recovery_waits_for_the_backoff(self):
        rig = await self._healthy()
        rig.health(0)
        await rig.mgr.tick()            # degrade at t=0, retry at t=1
        forwards_before = sum(len(t.forward_calls) for t in rig.made)
        await rig.mgr.tick()            # t=0: too early
        assert sum(len(t.forward_calls) for t in rig.made) == forwards_before
        rig.health(200)
        rig.now = 1.0
        await rig.mgr.tick()
        assert rig.states() == [State.DEGRADED, State.CONNECTING, State.TUNNELED, State.HEALTHY]

    async def test_recovery_re_forwards_and_drops_the_old_forward(self):
        rig = await self._healthy()
        old = rig.made[-1]
        rig.health(0, 200)
        await rig.mgr.tick()
        rig.now = 1.0
        await rig.mgr.tick()
        assert old.closed == 1
        assert rig.mgr.attachment("gpu01", SID)["state"] == "healthy"

    async def test_a_server_that_left_the_registry_is_gone_not_degraded(self):
        rig = await self._healthy()
        rig.health(0)
        await rig.mgr.tick()
        rig.listing()                   # the server is no longer announced
        rig.now = 1.0
        await rig.mgr.tick()
        assert rig.states() == [State.DEGRADED, State.GONE]
        assert rig.mgr.attachment("gpu01", SID) is None

    async def test_an_unreachable_host_stays_degraded_with_growing_backoff(self):
        rig = await self._healthy()
        rig.health(0)
        await rig.mgr.tick()
        rig.runs[tuple(LIST)] = [HostUnreachableError("down")]
        waits = []
        for _ in range(5):
            rig.now = rig.mgr._attachments[("gpu01", SID)].next_retry_at
            before = rig.now
            await rig.mgr.tick()
            waits.append(rig.mgr._attachments[("gpu01", SID)].next_retry_at - before)
        assert waits == [2, 4, 8, 8, 8], "exponential backoff capped at retry_max_s"
        assert rig.states() == [State.DEGRADED], "no event while nothing changes"
        assert "down" in rig.mgr.attachment("gpu01", SID)["detail"]

    async def test_a_failed_re_forward_goes_back_to_degraded(self):
        rig = await self._healthy()
        rig.health(0)
        await rig.mgr.tick()
        rig.forwards[SOCK] = [ForwardFailedError("fwd")]
        rig.now = 1.0
        await rig.mgr.tick()
        assert rig.states() == [State.DEGRADED, State.CONNECTING, State.DEGRADED]

    async def test_close_detaches_everything_and_stops_nothing(self):
        rig = await self._healthy()
        rig.mgr.start_monitor(interval_s=60)
        await rig.mgr.close()
        assert rig.states()[-1] is State.DISCONNECTED
        assert not any(path == "/shutdown" for *_, path in rig.http_calls)
        assert rig.mgr._monitor is None


# ---------------------------------------------------------------------------
# The remote shell snippets, run by a real sh
# ---------------------------------------------------------------------------

@posix_only
class TestRemoteScripts:
    @pytest.fixture
    def remote_home(self, monkeypatch):
        home = Path(tempfile.mkdtemp(prefix="ppx-home-"))
        bindir = home / ".local" / "bin"
        bindir.mkdir(parents=True)
        binary = bindir / "ppxai-server"
        binary.write_text("#!/bin/sh\necho ppxai-server 9.9.9\n")
        binary.chmod(0o755)
        (home / "my project").mkdir()
        monkeypatch.setenv("HOME", str(home))
        monkeypatch.setenv("PATH", "/usr/bin:/bin")   # the login PATH lacks ~/.local/bin
        yield home
        shutil.rmtree(home, ignore_errors=True)

    async def _run(self, argv):
        return await OpenSSHTransport("h", ssh_command=FAKE_SSH).run(argv, timeout=10)

    async def test_discovery_falls_back_to_the_install_location(self, remote_home):
        r = await self._run(["sh", "-c", _DISCOVER_SCRIPT, "sh", *_DEFAULT_CANDIDATES])
        assert r.rc == 0
        assert r.stdout.strip() == str(remote_home / ".local/bin/ppxai-server")

    async def test_discovery_reports_127_when_nothing_is_found(self, remote_home):
        r = await self._run(["sh", "-c", _DISCOVER_SCRIPT, "sh", "~/nope", "no-such-binary"])
        assert r.rc == 127

    async def test_cd_exec_expands_tilde_and_keeps_spaces(self, remote_home):
        r = await self._run(["sh", "-c", _CD_EXEC_SCRIPT, "sh", "~/my project", "pwd"])
        assert r.rc == 0
        assert os.path.realpath(r.stdout.strip()) == os.path.realpath(remote_home / "my project")

    async def test_cd_exec_fails_on_a_missing_workdir(self, remote_home):
        r = await self._run(["sh", "-c", _CD_EXEC_SCRIPT, "sh", "~/missing", "pwd"])
        assert r.rc != 0 and r.stdout == ""


# ---------------------------------------------------------------------------
# End to end: a real ppxai-server, through the fake ssh
# ---------------------------------------------------------------------------

@posix_only
@pytest.mark.slow
async def test_launch_attach_stop_against_a_real_server(tmp_path, monkeypatch):
    # A short runtime dir: AF_UNIX paths are capped (~104 bytes on macOS).
    runtime = Path(tempfile.mkdtemp(prefix="ppx-rt-", dir="/tmp"))
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(runtime))
    wrapper = tmp_path / "ppxai-server"
    wrapper.write_text(f'#!/bin/sh\nexec "{sys.executable}" -m ppxai.server.http "$@"\n')
    wrapper.chmod(wrapper.stat().st_mode | stat.S_IXUSR)
    workdir = tmp_path / "proj"
    workdir.mkdir()

    host = RemoteHost("wsl", "wsl", str(wrapper))
    mgr = RemoteSessionManager(
        [host], transport_factory=lambda h: OpenSSHTransport(h.ssh, ssh_command=FAKE_SSH),
        launch_timeout_s=90)
    events = []
    mgr.subscribe(events.append)
    server = None
    try:
        server = await mgr.launch("wsl", workdir=str(workdir), label="e2e")
        assert server.workdir == os.path.realpath(workdir) or server.workdir == str(workdir)
        listing = await mgr.servers("wsl")
        assert server.id in [s.id for s in listing.servers]

        view = await mgr.attach("wsl", server.id)
        assert view["state"] == "healthy", view
        endpoint, token = mgr.route("wsl", server.id)
        assert endpoint.kind == "uds"

        await mgr.stop("wsl", server.id)
        assert events[-1].state is State.GONE
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if server.id not in [s.id for s in (await mgr.servers("wsl")).servers]:
                break
            await asyncio.sleep(0.5)
        else:
            raise AssertionError("the server was still announced 30s after /shutdown")
        server = None
    finally:
        await mgr.close()
        if server is not None:
            try:
                os.kill(server.pid, 15)
            except ProcessLookupError:
                pass
        shutil.rmtree(runtime, ignore_errors=True)
