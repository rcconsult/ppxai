"""ADR 0013 S3 -- the remote-side contract: `--uds`, `--announce`, `--list`.

Two layers:

* The registry itself (`ppxai/server/registry.py`) on every platform: the
  field set is pinned per CONTRACT against a JSON fixture, entries are
  0600 and atomic, and `list_live` prunes what is dead.
* The real launch path, POSIX only (unix sockets): launch -> the printed
  entry -> `/health` over the socket with and without the token -> `--list`
  -> kill -> `--list` prunes. `--detach` separately: the launcher returns,
  the recorded pid is the SERVER's, and the server outlives the launcher.

HOME is the suite's throwaway home (conftest), so every registry path the
child server writes lands there, never in the developer's real ~/.ppxai.
"""

from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
import sys
import time
from pathlib import Path

import httpx
import pytest

from ppxai.server import http as server_http
from ppxai.server import registry

FIXTURES = Path(__file__).parent / "fixtures"
POSIX = sys.platform != "win32" and hasattr(__import__("socket"), "AF_UNIX")
posix_only = pytest.mark.skipif(not POSIX, reason="unix sockets: the S3 contract is POSIX-only")


# ---------------------------------------------------------------------------
# The contract is pinned
# ---------------------------------------------------------------------------

class TestTheContractIsPinned:
    def test_the_field_set_matches_this_contracts_fixture(self):
        path = FIXTURES / f"server_registry_contract_{registry.CONTRACT}.json"
        assert path.exists(), (
            f"CONTRACT is {registry.CONTRACT} but {path.name} does not exist. "
            "Adding a contract means adding its fixture.")
        pinned = json.loads(path.read_text(encoding="utf-8"))
        assert pinned["contract"] == registry.CONTRACT
        assert list(registry.ENTRY_FIELDS) == pinned["fields"], (
            "registry.ENTRY_FIELDS changed without a CONTRACT bump. A hub on "
            "another machine reads these entries; bump CONTRACT and add "
            f"server_registry_contract_{registry.CONTRACT + 1}.json instead.")

    def test_a_built_entry_carries_exactly_the_contract_fields(self, tmp_path):
        entry = registry.build_entry(server_id="abc", socket_path=tmp_path / "s.sock",
                                     token="t", workdir=str(tmp_path))
        assert tuple(entry) == registry.ENTRY_FIELDS
        assert entry["contract"] == registry.CONTRACT
        assert entry["pid"] == os.getpid()
        assert entry["started_at"].endswith("Z")
        assert entry["app_state_schema"]  # read from the shipped schema


# ---------------------------------------------------------------------------
# The registry on disk
# ---------------------------------------------------------------------------

def _entry(tmp_path, server_id="s1", pid=None, sock=None):
    return registry.build_entry(server_id=server_id,
                                socket_path=sock or tmp_path / f"{server_id}.sock",
                                token="secret", workdir=str(tmp_path), pid=pid)


class TestTheRegistryOnDisk:
    def test_entries_live_under_the_throwaway_home(self):
        assert registry.servers_dir().is_relative_to(Path.home())
        assert registry.servers_dir() == Path.home() / ".ppxai" / "run" / "servers"

    def test_write_then_read_round_trips(self, tmp_path):
        entry = _entry(tmp_path)
        registry.write_entry(entry)
        try:
            assert registry.read_entries() == [entry]
        finally:
            registry.remove_entry("s1")
        assert registry.read_entries() == []

    @posix_only
    def test_an_entry_is_0600_in_a_0700_directory(self, tmp_path):
        path = registry.write_entry(_entry(tmp_path))
        try:
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            assert stat.S_IMODE(path.parent.stat().st_mode) == 0o700
        finally:
            registry.remove_entry("s1")

    def test_unparseable_files_are_skipped_not_fatal(self, tmp_path):
        registry.servers_dir().mkdir(parents=True, exist_ok=True)
        junk = registry.servers_dir() / "junk.json"
        junk.write_text("{not json", encoding="utf-8")
        try:
            assert registry.read_entries() == []
        finally:
            junk.unlink()

    def test_list_live_prunes_a_dead_pid(self, tmp_path):
        dead = subprocess.Popen([sys.executable, "-c", "pass"])
        dead.wait()
        registry.write_entry(_entry(tmp_path, "dead", pid=dead.pid))
        assert registry.list_live(prune=True) == []
        assert not registry.entry_path("dead").exists()

    def test_list_live_prunes_a_live_pid_whose_socket_is_gone(self, tmp_path):
        registry.write_entry(_entry(tmp_path, "nosock", pid=os.getpid(),
                                    sock=tmp_path / "missing.sock"))
        assert registry.list_live(prune=True) == []
        assert not registry.entry_path("nosock").exists()

    def test_list_without_prune_keeps_dead_entries(self, tmp_path):
        registry.write_entry(_entry(tmp_path, "keep", pid=os.getpid(),
                                    sock=tmp_path / "missing.sock"))
        try:
            assert registry.list_live(prune=False) == []
            assert registry.entry_path("keep").exists()
        finally:
            registry.remove_entry("keep")


# ---------------------------------------------------------------------------
# The CLI refuses what the contract does not allow
# ---------------------------------------------------------------------------

def _cli(*args, timeout=60):
    return subprocess.run([sys.executable, "-m", "ppxai.server.http", *args],
                          capture_output=True, text=True, timeout=timeout)


def _refused(monkeypatch, capsys, *args) -> str:
    """Run the CLI in-process and return stderr; it must exit 2.

    Every refusal returns before anything is bound, forked or initialized,
    so there is nothing to isolate -- and a subprocess would pay a full
    server import (~11s on Windows) per case just to print one line.
    """
    monkeypatch.setattr(sys, "argv", ["ppxai-server", *args])
    with pytest.raises(SystemExit) as exc:
        server_http.run_server()
    assert exc.value.code == 2
    return capsys.readouterr().err


class TestTheCliRefusesMisuse:
    def test_announce_without_uds_is_refused(self, monkeypatch, capsys):
        assert "--uds" in _refused(monkeypatch, capsys, "--announce")

    def test_detach_without_announce_is_refused(self, monkeypatch, capsys):
        assert "--announce" in _refused(monkeypatch, capsys, "--uds", "--detach")

    def test_reload_with_uds_is_refused(self, monkeypatch, capsys):
        assert "--reload" in _refused(monkeypatch, capsys, "--uds", "--reload")

    @pytest.mark.skipif(POSIX, reason="the Windows refusal")
    def test_windows_refuses_uds_with_a_clear_message(self, monkeypatch, capsys):
        assert "POSIX" in _refused(monkeypatch, capsys, "--uds", "--announce")

    def test_list_with_no_servers_says_so(self):
        """The one subprocess case: it proves the real `python -m` entry
        point, on every platform (the launch tests below are POSIX-only)."""
        proc = _cli("--list", "--json")
        assert proc.returncode == 0, proc.stderr
        assert json.loads(proc.stdout) == []


# ---------------------------------------------------------------------------
# The real launch path (POSIX)
# ---------------------------------------------------------------------------

def _read_json_block(stream, deadline_s=60.0) -> dict:
    """Read the first JSON object the server prints (before uvicorn's logs)."""
    lines, deadline = [], time.time() + deadline_s
    while time.time() < deadline:
        line = stream.readline()
        if not line:
            break
        if not lines and not line.startswith("{"):
            continue
        lines.append(line)
        if line.rstrip() == "}":
            return json.loads("".join(lines))
    raise AssertionError(f"no JSON entry on stdout; got {''.join(lines)!r}")


def _uds_client(sock: str) -> httpx.Client:
    return httpx.Client(transport=httpx.HTTPTransport(uds=sock), timeout=5.0)


def _wait_healthy(sock: str, token: str, deadline_s=60.0) -> None:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if registry.socket_answers(sock, token):
            return
        time.sleep(0.25)
    raise AssertionError(f"server on {sock} never answered /health")


def _wait_gone(path: Path, deadline_s=20.0) -> bool:
    deadline = time.time() + deadline_s
    while time.time() < deadline:
        if not path.exists():
            return True
        time.sleep(0.2)
    return False


def _announce(workdir: Path):
    """Launch an announced server; yield (proc, entry); always reap it."""
    # A short path: AF_UNIX paths are capped (~104 bytes on macOS).
    sock_dir = Path("/tmp") / f"ppxai-t-{os.getpid()}-{time.monotonic_ns() % 10**6}"
    sock = sock_dir / "s.sock"
    proc = subprocess.Popen(
        [sys.executable, "-m", "ppxai.server.http", "--uds", str(sock),
         "--announce", "--label", "pytest"],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, cwd=str(workdir))
    try:
        entry = _read_json_block(proc.stdout)
        _wait_healthy(entry["socket"], entry["token"])
        yield proc, entry
    finally:
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=15)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        proc.stdout.close()


@posix_only
@pytest.mark.slow
class TestAnnouncedServer:
    """Read-only checks share ONE server: a boot is most of each test's cost."""

    @pytest.fixture(scope="class")
    def announced(self, tmp_path_factory):
        yield from _announce(tmp_path_factory.mktemp("announced"))

    def test_the_printed_entry_is_the_registry_entry(self, announced):
        proc, entry = announced
        assert tuple(entry) == registry.ENTRY_FIELDS
        assert entry["pid"] == proc.pid  # the SERVER's pid, not a launcher's
        assert entry["label"] == "pytest"
        on_disk = json.loads(registry.entry_path(entry["id"]).read_text(encoding="utf-8"))
        assert on_disk == entry

    def test_the_socket_is_0600_in_a_0700_directory(self, announced):
        _, entry = announced
        sock = Path(entry["socket"])
        assert stat.S_IMODE(sock.stat().st_mode) == 0o600
        assert stat.S_IMODE(sock.parent.stat().st_mode) == 0o700

    def test_even_health_needs_the_token(self, announced):
        """Auth is ON for an announced server and /health is not exempt from
        it (only from the Host check) -- so liveness probes, --list
        included, must present the entry's token."""
        _, entry = announced
        with _uds_client(entry["socket"]) as c:
            assert c.get("http://localhost/health").status_code == 401
            right = {"Authorization": f"Bearer {entry['token']}"}
            assert c.get("http://localhost/health", headers=right).status_code == 200

    def test_the_api_needs_the_announced_token(self, announced):
        _, entry = announced
        with _uds_client(entry["socket"]) as c:
            assert c.get("http://localhost/state").status_code == 401
            wrong = {"Authorization": "Bearer not-the-token"}
            assert c.get("http://localhost/state", headers=wrong).status_code == 401
            right = {"Authorization": f"Bearer {entry['token']}"}
            assert c.get("http://localhost/state", headers=right).status_code == 200


@posix_only
@pytest.mark.slow
class TestAnnouncedServerEnds:
    """Each test here ends its server, so each gets its own."""

    @pytest.fixture
    def announced(self, tmp_path):
        yield from _announce(tmp_path)

    def test_list_shows_it_then_prunes_it_after_a_kill(self, announced):
        proc, entry = announced
        listed = json.loads(_cli("--list", "--json").stdout)
        assert [e["id"] for e in listed] == [entry["id"]]
        proc.kill()  # no cleanup runs: the entry and socket are left behind
        proc.wait()
        assert registry.entry_path(entry["id"]).exists()
        assert json.loads(_cli("--list", "--json").stdout) == []
        assert not registry.entry_path(entry["id"]).exists()

    def test_a_clean_stop_removes_the_entry_and_socket(self, announced):
        proc, entry = announced
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        assert _wait_gone(registry.entry_path(entry["id"]))
        assert _wait_gone(Path(entry["socket"]))


@posix_only
@pytest.mark.slow
def test_detach_returns_and_the_server_outlives_the_launcher(tmp_path):
    sock = Path("/tmp") / f"ppxai-d-{os.getpid()}-{time.monotonic_ns() % 10**6}" / "s.sock"
    launcher = subprocess.run(
        [sys.executable, "-m", "ppxai.server.http", "--uds", str(sock),
         "--announce", "--detach"],
        capture_output=True, text=True, timeout=90, cwd=str(tmp_path))
    assert launcher.returncode == 0, launcher.stderr
    entry = json.loads(launcher.stdout)
    try:
        assert entry["pid"] != os.getpid()
        _wait_healthy(entry["socket"], entry["token"])
        listed = json.loads(_cli("--list", "--json").stdout)
        assert [e["id"] for e in listed] == [entry["id"]]
    finally:
        try:
            os.kill(entry["pid"], signal.SIGTERM)
        except ProcessLookupError:
            pass
    assert _wait_gone(registry.entry_path(entry["id"]))
