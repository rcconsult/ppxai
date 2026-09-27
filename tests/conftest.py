import ipaddress
import json
import os
import shutil
import socket
import sys
import tempfile
import time
from pathlib import Path

import pytest
from _pytest.terminal import TerminalReporter
from dotenv import load_dotenv

#: The config this repository SHIPS. The suite's verdicts are pinned to it.
REPO_CONFIG_FILE = Path(__file__).resolve().parent.parent / "ppxai-config.json"

# The extension's esbuild, for the tests that compile real TS modules and run
# them under Node. `.bin/esbuild` is a POSIX shell script; Windows cannot
# execute it (WinError 193) and needs npm's `.cmd` shim instead.
ESBUILD = (Path(__file__).resolve().parent.parent / "vscode-extension"
           / "node_modules" / ".bin"
           / ("esbuild.cmd" if sys.platform == "win32" else "esbuild"))

#: The developer's REAL home, captured at conftest IMPORT time — i.e. before
#: `pytest_configure` points `HOME` somewhere else. Everything downstream
#: compares against this, so "is this path in the user's real data directory?"
#: stays answerable for the whole run.
REAL_HOME = Path(os.path.expanduser("~")).resolve()
REAL_PPXAI_HOME = REAL_HOME / ".ppxai"

#: The throwaway home the suite runs inside. Assigned by
#: `_redirect_home_to_tmp()`; `None` only if that never ran.
FAKE_HOME: Path | None = None

#: Set `PPXAI_TEST_KEEP_HOME=1` to keep the throwaway home after the run
#: (it is printed in the terminal summary) instead of deleting it. Used to
#: MEASURE what the suite writes — see docs/debt-inventory.md Item 78.
_KEEP_HOME_ENV = "PPXAI_TEST_KEEP_HOME"


def _redirect_home_to_tmp() -> Path:
    """Point `HOME` at a fresh throwaway directory. Returns it.

    THE ROOT FIX FOR ITEM 78. The suite was writing into the developer's real
    `~/.ppxai`: ~14,900 empty `sessions/checkpoints/session_<ts>/` directories
    had accumulated there (~100 per full run), plus `.preview-cache/` entries
    with real PNG content, plus `runs/`, `sessions/` and `logs/`. No fixture
    could tear that up, because none of it is a fixture's: the checkpoint
    directory is a CONSTRUCTOR side effect of ordinary session creation
    (`FileCheckpointBackend.__init__`), and deleting from a developer's live
    data directory would be the wrong repair anyway. The fix is that the suite
    never reaches the real home in the first place.

    Why `HOME` and not a list of monkeypatched constants: the leaks come from
    BOTH halves of the same hazard and a constant list only covers one.

      * import-time constants — `PPXAI_HOME`/`SESSIONS_DIR` (config/loader.py),
        `SESSION_STATE_FILE` (engine/session.py), `_PREVIEW_CACHE_ROOT`
        (server/routes/files.py), `HINT_TEMPLATES_FILE`, `_DEFAULT_STAGING_DIR`,
        `PREVIEW_LOGS_DIR` — plus every module that did `from … import
        SESSIONS_DIR` and holds its OWN binding (`ppxai/checkpoint.py:25`), so
        patching the defining module alone does not redirect the importer;
      * call-time `Path.home()` — `SessionManager.__init__`'s default
        `sessions_dir`/`exports_dir` (engine/session.py:315-317), the logger's
        `~/.ppxai/logs` (common/logger.py:135), `usage.py`, `usage_events.py`,
        `server/routes/static.py`, `engine/bootstrap.py:708`, … A module
        attribute sweep cannot see any of these; nothing is bound.

    Setting `HOME` here covers both, because this hook runs before ANY ppxai
    module is imported (asserted below), so even the import-time constants
    resolve into the throwaway home from the start.

    Read CLAUDE.md's "monkeypatch HOME does NOT work" note carefully — it is
    about patching HOME *after* import, which is a no-op for a constant already
    resolved. Doing it before the first import is the one case that does work,
    and is exactly what `tests/test_consumer_import_surface.py` already does
    for its subprocess probes.

    The throwaway home is `.resolve()`d so `Path.home()` and
    `Path.home().resolve()` are the same string; on macOS `tempfile` hands back
    `/var/folders/…`, whose real path is `/private/var/folders/…`, and tests
    that compare a resolved path against `Path.home()` (tests/test_tui.py:472)
    would otherwise fail on the symlink alone.

    The real `.env` is deliberately NOT copied in. `pytest_configure` has
    already `load_dotenv`'d it into `os.environ` before this runs, so every
    key and `SSL_VERIFY` is visible to the process and to spawned children;
    a second copy ON DISK would be a plaintext duplicate of the developer's
    provider keys in a temp directory that survives a crash, a `kill -9` or
    `PPXAI_TEST_KEEP_HOME=1`. The throwaway home therefore has no `.env`,
    which is also what CI has. The repo config IS copied, to
    `ppxai-config.json`, so a fallthrough lands on the same pinned verdict as
    `PPXAI_CONFIG_FILE` (Item 69) rather than seeding an example config.
    """
    fake_home = Path(tempfile.mkdtemp(prefix="ppxai-test-home-")).resolve()
    ppxai_home = fake_home / ".ppxai"
    ppxai_home.mkdir(parents=True, exist_ok=True)

    if REPO_CONFIG_FILE.is_file():
        shutil.copyfile(REPO_CONFIG_FILE, ppxai_home / "ppxai-config.json")

    # `~/.ppxai/web` is the INSTALLED web UI, 8 MB of static assets that only
    # an install writes. `tests/test_schema_endpoint.py` skips its three
    # schema-injection tests when it is absent ("Web UI not installed at
    # ~/.ppxai/web/"), so without this the redirect would silently turn three
    # passing tests on a developer host into skips -- a coverage loss that
    # looks like nothing at all in the summary line.
    #
    # A SYMLINK rather than a copy, deliberately: 8 MB per pytest invocation
    # is a real cost on the short targeted runs people actually do. Nothing in
    # `ppxai/` writes under this directory -- `server/routes/static.py` only
    # serves from it (`WEB_UI_DIR`), and `grep -rn "web_dir\|WEB_DIR" ppxai/`
    # finds no write, mkdir, copy or unlink. If that ever changes, copy
    # instead; the symlink is the one thread back to the real home.
    #
    # Windows without Developer Mode refuses the symlink (WinError 1314), and
    # this runs in `pytest_configure`, so an unhandled error there kills
    # EVERY pytest invocation on such a host. Fall back to a copy: slower,
    # but the copy lives inside the throwaway home `pytest_unconfigure`
    # removes, so nothing can reach back to the real one.
    real_web = REAL_PPXAI_HOME / "web"
    if real_web.is_dir():
        try:
            (ppxai_home / "web").symlink_to(real_web, target_is_directory=True)
        except OSError:
            shutil.copytree(real_web, ppxai_home / "web")

    os.environ["HOME"] = str(fake_home)
    # Windows: `os.path.expanduser("~")` prefers USERPROFILE, then
    # HOMEDRIVE+HOMEPATH, and only then HOME. UNVERIFIED on Windows — this
    # host is macOS; see the Item 78 report.
    os.environ["USERPROFILE"] = str(fake_home)
    os.environ.pop("HOMEDRIVE", None)
    os.environ.pop("HOMEPATH", None)
    return fake_home


def _fake_equivalent(value: Path) -> Path | None:
    """The throwaway-home twin of `value`, or None if it isn't under REAL_HOME."""
    if FAKE_HOME is None:
        return None
    try:
        relative = value.relative_to(REAL_HOME)
    except ValueError:
        return None
    return FAKE_HOME / relative


def ppxai_paths_still_in_the_real_ppxai_home() -> dict[str, Path]:
    """Every loaded `ppxai.*` module attribute that is a Path in `~/.ppxai`.

    The measurement the Item 78 fence asserts is empty, and the input to
    `rebind_home_derived_paths()`. Derived by walking `sys.modules` rather than
    from a hand-written list of constants, so a constant added tomorrow is
    covered without anyone remembering to add a row.

    Scoped to the real `~/.ppxai`, not to the whole real home, on purpose:
    `~/.ppxai` is the user state Item 78 is about, and a repository checked
    out inside the home directory (as this one is) would otherwise make every
    legitimate repo-relative constant read as a violation.
    """
    found: dict[str, Path] = {}
    for module_name, module in list(sys.modules.items()):
        if module_name != "ppxai" and not module_name.startswith("ppxai."):
            continue
        if module is None:
            continue
        try:
            members = list(vars(module).items())
        except TypeError:
            continue
        for attr, value in members:
            if isinstance(value, Path):
                candidates = [(attr, value)]
            elif isinstance(value, (list, tuple)):
                candidates = [
                    (f"{attr}[{i}]", item)
                    for i, item in enumerate(value)
                    if isinstance(item, Path)
                ]
            else:
                continue
            for label, path in candidates:
                try:
                    path.relative_to(REAL_PPXAI_HOME)
                except ValueError:
                    continue
                found[f"{module_name}.{label}"] = path
    return found


def rebind_home_derived_paths() -> list[str]:
    """Repoint any real-home Path still bound on a loaded ppxai module.

    Belt-and-braces behind `_redirect_home_to_tmp()`: with `HOME` moved before
    the first ppxai import there should be nothing to do, and the Item 78 fence
    asserts exactly that. It exists so that a module imported through some path
    that resolved `Path.home()` earlier (a cached constant carried in by a
    plugin, a future conftest that imports ppxai at top level) is corrected
    rather than silently writing to the developer's home.

    Only rewrites values that are under the REAL home, so a test's own
    monkeypatched tmp path is never clobbered.
    """
    rebound: list[str] = []
    for qualified, value in ppxai_paths_still_in_the_real_ppxai_home().items():
        module_name, _, label = qualified.rpartition(".")
        module = sys.modules.get(module_name)
        if module is None or "[" in label:
            # Container elements are reported, not rewritten: rebuilding a
            # list in place would be guessing at the owner's intent.
            continue
        replacement = _fake_equivalent(value)
        if replacement is None:
            continue
        setattr(module, label, replacement)
        rebound.append(qualified)
    return rebound


def pytest_configure(config):
    """Configure pytest before test collection.

    This is the earliest hook that runs before any test modules are imported.
    We load user's .env here so SSL_VERIFY and other env vars are available
    when provider modules are imported.
    """
    global FAKE_HOME, _pytest_config

    config._test_durations = {}  # nodeid -> {setup, call, teardown} seconds
    _pytest_config = config
    config.addinivalue_line(
        "markers",
        "network: the test deliberately reaches a non-loopback host "
        "(exempt from the no-network guard below)",
    )

    # Load user's .ppxai/.env for integration tests that need SSL_VERIFY=false
    # This must happen before any ppxai modules are imported -- and before the
    # HOME redirect below, which is what makes `~` stop meaning the real home.
    user_env_path = os.path.expanduser('~/.ppxai/.env')
    if os.path.exists(user_env_path):
        load_dotenv(dotenv_path=user_env_path, override=True)

    # ---------------------------------------------------------------
    # Debt Item 78: the suite must not be able to touch the real ~/.ppxai.
    #
    # Ordering is the whole mechanism. `_redirect_home_to_tmp()` only works
    # because no ppxai module has been imported yet, so every module-level
    # `Path.home()` constant resolves into the throwaway home when it IS
    # imported. Assert that premise rather than trusting it: if a future
    # plugin or conftest import pulls ppxai in earlier, the redirect would
    # half-apply and the leak would come back silently.
    # ---------------------------------------------------------------
    already_imported = sorted(
        name for name in sys.modules
        if name == "ppxai" or name.startswith("ppxai.")
    )
    FAKE_HOME = _redirect_home_to_tmp()
    config._ppxai_fake_home = FAKE_HOME
    config._ppxai_preimported = already_imported

    # ---------------------------------------------------------------
    # Debt Item 69: pin the config SOURCE before anything reads it.
    #
    # `find_config_file()` resolves PPXAI_CONFIG_FILE -> ./ppxai-config.json
    # -> ~/.ppxai/ppxai-config.json and takes the FIRST hit. Nothing pinned
    # it, so a test that reached provider config got whichever file the
    # developer happened to have, and its verdict varied by machine, by cwd,
    # and by the state of a file that is not under version control.
    #
    # That is not theoretical and it failed in the DANGEROUS direction. On
    # 2026-09-01 `test_the_message_names_the_capable_models` passed in the
    # main checkout and failed in a worktree at the same commit: the
    # developer's ~/.ppxai config still carried sonar-pro / sonar-reasoning-pro,
    # retired from both shipped configs in e6c366b9. The stale personal file
    # MASKED a real regression. A machine-specific green is indistinguishable
    # from a correct one until CI, a fresh checkout, or a user finds it.
    #
    # Set here rather than in a fixture because `initialize()` below reads
    # config during collection, before any fixture runs. Respects an explicit
    # override so a developer can still aim the suite at another config.
    #
    # The pin names a byte-identical COPY in the throwaway home, not the
    # tracked file: `find_writable_config_file()` treats PPXAI_CONFIG_FILE as
    # writable on purpose, so pinning the repo file let `/debug-log` (the
    # route smoke test) rewrite it -- invisibly on POSIX, with CRLF on
    # Windows (found 2026-09-27). Reads are identical; writes land in the
    # copy. `pytest_sessionfinish` fails the run if the tracked file changes.
    # ---------------------------------------------------------------
    if not os.environ.get("PPXAI_CONFIG_FILE") and REPO_CONFIG_FILE.exists():
        pinned = FAKE_HOME / "pinned" / "ppxai-config.json"
        pinned.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(REPO_CONFIG_FILE, pinned)
        os.environ["PPXAI_CONFIG_FILE"] = str(pinned)
    config._ppxai_repo_config_bytes = (
        REPO_CONFIG_FILE.read_bytes() if REPO_CONFIG_FILE.exists() else None)

    # Initialize config system (v1.15.3: DAG-based init)
    from ppxai.config import initialize
    initialize()

    # Item 78, second half: correct anything the redirect could not have
    # covered. Expected to rebind NOTHING (the fence in
    # tests/test_home_hermeticity.py asserts the real-home set is empty);
    # recorded on `config` so that fence can report what had to be fixed up.
    config._ppxai_rebound = rebind_home_derived_paths()


def pytest_sessionfinish(session, exitstatus):
    """Fail the run if any test rewrote the tracked ppxai-config.json."""
    before = getattr(session.config, "_ppxai_repo_config_bytes", None)
    if before is None or not REPO_CONFIG_FILE.exists():
        return
    if REPO_CONFIG_FILE.read_bytes() != before:
        reporter = session.config.pluginmanager.get_plugin("terminalreporter")
        if reporter is not None:
            reporter.ensure_newline()
            reporter.write_line(
                f"FAILED: the test run modified the tracked {REPO_CONFIG_FILE.name}. "
                "Something wrote to it directly or through a PPXAI_CONFIG_FILE "
                "pointing at it; restore it with `git checkout -- "
                f"{REPO_CONFIG_FILE.name}` and find the writer.", red=True)
        session.exitstatus = pytest.ExitCode.TESTS_FAILED


def pytest_unconfigure(config):
    """Delete the throwaway home unless the developer asked to keep it."""
    fake_home = getattr(config, "_ppxai_fake_home", None)
    if fake_home is None or os.environ.get(_KEEP_HOME_ENV):
        return
    shutil.rmtree(fake_home, ignore_errors=True)


@pytest.fixture(autouse=True, scope="session")
def _the_developers_config_is_unreachable():
    """No test may resolve the real `~/.ppxai/ppxai-config.json`.

    The pin in `pytest_configure` is necessary but not sufficient: a test
    that clears the environment (`patch.dict(os.environ, {}, clear=True)` is
    common here) and runs from a cwd without a project config falls straight
    through to the user's file again. This closes that hole by redirecting
    the constant the fallback reads.

    `find_config_file()` reads `USER_CONFIG_FILE` as a module global at CALL
    time, so patching it on its defining module reaches every caller — even
    the modules that did `from .loader import find_config_file` and hold
    their own binding to the function. Patching `HOME` would NOT work: the
    constant is `PPXAI_HOME / "ppxai-config.json"` evaluated at import.

    Pointed at a path that does not exist, so the fallback yields None and
    callers take their documented defaults — deterministic, and identical on
    every machine. Writers are covered too: `find_writable_config_file()`
    reads the same constant, so a stray write lands in tmp instead of the
    developer's home.

    Session-scoped: this is a property of the whole run, and a per-test
    fixture would re-patch 5,700 times for no benefit. A test that wants its
    own user config still patches the constant itself; the inner patch wins
    and unwinds back to this one.
    """
    from _pytest.monkeypatch import MonkeyPatch

    mp = MonkeyPatch()
    try:
        from ppxai.config import loader

        unreachable = (
            Path(__file__).resolve().parent
            / "_not-the-developers-home"
            / "ppxai-config.json"
        )
        mp.setattr(loader, "USER_CONFIG_FILE", unreachable)
    except (ImportError, AttributeError):
        # Config package not importable in this env — nothing to protect.
        pass
    yield
    mp.undo()


@pytest.fixture(autouse=True)
def _isolate_session_state_pointer(tmp_path_factory, monkeypatch):
    """No test may write the user's real `~/.ppxai/session-state.json`.

    THE RECURRING TUI REGRESSION. `session.py` defines

        SESSION_STATE_FILE = Path.home() / ".ppxai" / "session-state.json"

    at MODULE level, so it is resolved at import time. A test that redirects
    `sessions_dir`/`exports_dir` through the SessionManager constructor — or
    that monkeypatches HOME after import — still writes the real pointer.
    `test_v1_session_migration.py` does exactly that: it isolates the session
    directory and never touches SESSION_STATE_FILE.

    The consequence is invisible during the run and shows up later as "session
    restore is broken" in the TUIs: the pointer now names a fixture session
    (`v1_with_image`, working_dir `/home/user/projects/ops`), the TUI finds it
    missing or wrong, falls back to newest-on-disk, hits a 0-message session
    and restores nothing. Web/VSCode survive because the server resolves
    sessions through its own manager.

    Demonstrated 2026-08-09: `pytest tests/test_v1_session_migration.py`
    alone moved the real file's mtime from 22:58:50 to 23:08:06.

    Autouse and suite-wide ON PURPOSE. Fixing the one guilty test would leave
    the next one free to reintroduce it, and this has recurred often enough to
    be treated as a class of bug rather than an incident. Tests that need
    their own pointer still patch it themselves — an inner patch wins and
    unwinds back to this tmp path.
    """
    state = tmp_path_factory.mktemp("ppxai-state") / "session-state.json"
    try:
        monkeypatch.setattr("ppxai.engine.session.SESSION_STATE_FILE", state)
    except (ImportError, AttributeError):
        # Engine not importable in this env — nothing to protect.
        pass
    yield


@pytest.fixture(autouse=True)
def reset_config_after_test():
    """Reset PROVIDERS/MODELS after each test for isolation.

    v1.15.3: With DAG-based init, PROVIDERS/MODELS are module-level dicts
    that persist across tests. This fixture ensures each test starts with
    a clean config state by re-initializing after each test.
    """
    yield  # Run the test
    # After test completes, reload config to reset PROVIDERS/MODELS
    from ppxai.config import initialize
    initialize()


@pytest.fixture(autouse=True)
def _auth_off_by_default(monkeypatch):
    """Pin server auth OFF (env-only, unset) for the whole suite by default.

    v1.19.0 (Inc 8a) enforces auth whenever a mutable `file` token store is
    configured. On a DEV HOST whose ~/.ppxai/ppxai-config.json configures one
    (e.g. after trialing /v1/tokens), every TestClient call against the real
    `app` would otherwise get 401 — a host-dependent failure unrelated to the
    test under inspection. Resetting the secret-provider singleton to a single
    env-var provider (with the var unset) makes the suite host-independent:
    auth is off unless a test opts in.

    Tests that exercise auth/authz (test_auth_middleware, test_tokens_v1_route,
    test_agent_run_authz, …) install their OWN provider chain via
    monkeypatch.setattr(state, "_secret_provider", …) inside the test/fixture,
    which overrides this default for that test. After the test, the singleton
    is dropped so the next get_secret_provider() rebuilds from config.
    """
    monkeypatch.delenv("PPXAI_API_TOKEN", raising=False)
    try:
        import ppxai.server.state as _state
        from ppxai.server.secrets import EnvSecretProvider, ProviderChain

        monkeypatch.setattr(
            _state, "_secret_provider", ProviderChain([EnvSecretProvider()])
        )
    except Exception:
        # Server extras not importable in this env — nothing to pin.
        pass
    yield
    try:
        import ppxai.server.state as _state
        _state._secret_provider = None
    except Exception:
        pass


# ---------------------------------------------------------------------------
# No test reaches the network.
#
# pytest_configure loads the developer's ~/.ppxai/.env, API keys included, so
# a test that drives a real provider path makes a real, BILLED call -- and it
# does so silently, because provider code turns the connection into an ERROR
# event instead of raising. Measured 2026-09-27: 19 tests in three files
# (test_auth_middleware, test_usage_integration, test_agent_task_validation)
# called api.perplexity.ai, generativelanguage.googleapis.com and
# api.openai.com on every run.
#
# The guard blocks name resolution AND connects to anything that is not
# loopback or a unix socket. getaddrinfo is the one choke point every client
# passes through: on Windows asyncio's proactor loop connects via ConnectEx
# and never calls socket.connect. A blocked attempt is RECORDED and the test
# fails at teardown naming the host -- the provider swallowing the error does
# not hide it.
#
# Opt in deliberately: `@pytest.mark.network`, or PPXAI_TESTS_ALLOW_NETWORK=1
# for the whole run. Subprocesses a test spawns are not covered.
# ---------------------------------------------------------------------------

_LOCAL_NAMES = frozenset({None, "", "localhost", "testserver", "testclient"})
_network_allowed = os.environ.get("PPXAI_TESTS_ALLOW_NETWORK") == "1"
_network_attempts: list[str] = []


def _is_local(host) -> bool:
    if isinstance(host, bytes):
        host = host.decode("ascii", "replace")
    if host in _LOCAL_NAMES:
        return True
    try:
        return ipaddress.ip_address(str(host).split("%", 1)[0]).is_loopback
    except ValueError:
        return False


class NetworkBlockedError(OSError):
    """A test tried to reach a non-loopback host (see the guard in conftest)."""


_real_getaddrinfo = socket.getaddrinfo
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex


def _refuse(target: str):
    _network_attempts.append(target)
    raise NetworkBlockedError(
        f"test tried to reach {target}; tests must not call the network "
        "(mark it @pytest.mark.network if that is the point)")


def _guarded_getaddrinfo(host, port, *args, **kwargs):
    if not _network_allowed and not _is_local(host):
        _refuse(f"{host}:{port}")
    return _real_getaddrinfo(host, port, *args, **kwargs)


def _guarded_connect(self, address):
    if (not _network_allowed and self.family != getattr(socket, "AF_UNIX", None)
            and isinstance(address, tuple) and not _is_local(address[0])):
        _refuse(f"{address[0]}:{address[1]}")
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    if (not _network_allowed and self.family != getattr(socket, "AF_UNIX", None)
            and isinstance(address, tuple) and not _is_local(address[0])):
        _refuse(f"{address[0]}:{address[1]}")
    return _real_connect_ex(self, address)


socket.getaddrinfo = _guarded_getaddrinfo
socket.socket.connect = _guarded_connect
socket.socket.connect_ex = _guarded_connect_ex


@pytest.fixture(autouse=True)
def _no_network(request):
    global _network_allowed
    opted_in = request.node.get_closest_marker("network") is not None
    previous = _network_allowed
    _network_allowed = previous or opted_in
    _network_attempts.clear()
    yield
    _network_allowed = previous
    if _network_attempts:
        attempts = sorted(set(_network_attempts))
        _network_attempts.clear()
        pytest.fail(
            "blocked network access: " + ", ".join(attempts) + ". Tests must "
            "not call real services (they are billed, slow and flaky); use a "
            "fake, or mark the test @pytest.mark.network if the network IS "
            "the subject.", pytrace=False)


@pytest.fixture(autouse=True)
def _no_ssrf_dns(monkeypatch):
    """The egress policy's SSRF guard resolves every allowlisted host
    (`network_policy._host_resolves_to_blocked_ip`), so any test that drives
    `NetworkPolicy.check` did live DNS for api.github.com, api.perplexity.ai,
    wttr.in and friends. Default it to "not blocked", as test_network_policy
    long did for itself; a test that exercises the guard patches it back
    explicitly. The string target keeps this free of a function-level import.
    """
    monkeypatch.setattr(
        "ppxai.engine.tools.network_policy._host_resolves_to_blocked_ip",
        lambda host: False)


# ---------------------------------------------------------------------------
# One CA-loaded SSL context for every default-TLS httpx client in the suite.
#
# Every `httpx.Client()` -- and so every FastAPI `TestClient`, and every
# module-level `httpx.get()` -- builds a fresh SSL context from certifi,
# even for plain http:// or the in-process ASGI transport. Under the
# OpenSSL 3.0 that Windows CPython ships that is ~0.8s of CPU per client
# (measured 2026-09-27: 5 clients, 4.2s), and it was most of the suite's
# fixture-setup time -- debt Item 83. Tests never need a fresh one, so
# clients built with the DEFAULTS share one per SSL_CERT_FILE/SSL_CERT_DIR
# value; anything passing its own `verify`/`cert` takes the real path.
# Test-only: production builds its clients from `ppxai.config.tls`.
# ---------------------------------------------------------------------------

import httpx._transports.default as _httpx_transport  # noqa: E402

REAL_CREATE_SSL_CONTEXT = _httpx_transport.create_ssl_context
_ssl_context_cache: dict = {}


def _shared_create_ssl_context(verify=True, cert=None, trust_env=True):
    if verify is not True or cert is not None:
        return REAL_CREATE_SSL_CONTEXT(verify=verify, cert=cert, trust_env=trust_env)
    key = (trust_env, os.environ.get("SSL_CERT_FILE"), os.environ.get("SSL_CERT_DIR"))
    ctx = _ssl_context_cache.get(key)
    if ctx is None:
        ctx = _ssl_context_cache[key] = REAL_CREATE_SSL_CONTEXT(
            verify=verify, cert=cert, trust_env=trust_env)
    return ctx


_httpx_transport.create_ssl_context = _shared_create_ssl_context


_libreoffice_allowed = os.environ.get("PPXAI_TESTS_ALLOW_LIBREOFFICE") == "1"


def pytest_collection_modifyitems(config, items):
    """Real-LibreOffice tests are opt-in (see `_no_libreoffice`)."""
    if _libreoffice_allowed:
        return
    skip = pytest.mark.skip(
        reason="drives the real LibreOffice; set PPXAI_TESTS_ALLOW_LIBREOFFICE=1")
    for item in items:
        if item.get_closest_marker("libreoffice") is not None:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def _no_libreoffice(request, monkeypatch):
    """LibreOffice is invisible to tests unless they opt in.

    A developer box with LibreOffice installed ran it headless from the
    office-preview tests -- 38s for one PPTX render, several instances at
    once under xdist, and on Windows a "Waiting for printer connection"
    dialog when the default printer was an unreachable network (WSD) one
    (2026-09-27). Discovery reads `_PATH_NAMES` and `_well_known_paths()` at
    call time, so emptying both makes every caller take the documented
    no-LibreOffice path -- the path CI takes anyway.

    `@pytest.mark.libreoffice` tests render for real (and are skipped unless
    PPXAI_TESTS_ALLOW_LIBREOFFICE=1); `@pytest.mark.libreoffice_discovery`
    tests exercise the resolver itself with their own doubles.
    """
    node = request.node
    if (node.get_closest_marker("libreoffice") is not None
            or node.get_closest_marker("libreoffice_discovery") is not None):
        return
    monkeypatch.setattr("ppxai.common.libreoffice._PATH_NAMES", ())
    monkeypatch.setattr("ppxai.common.libreoffice._well_known_paths", lambda: [])
    monkeypatch.delenv("PPXAI_LIBREOFFICE", raising=False)


@pytest.fixture
def fake_providers(monkeypatch):
    """Every provider the test builds answers locally ("pong", counted
    tokens) -- for tests that drive a real chat/oneshot path but are not
    ABOUT the provider. See tests/fake_provider.py."""
    from tests import fake_provider
    return fake_provider.install(monkeypatch)


@pytest.fixture
def isolated_working_dir(tmp_path):
    """A scratch working directory for tests that must not inherit the host's.

    Use with `pin_server_working_dir()` for tests that spawn a real server.
    """
    wd = tmp_path / "workdir"
    wd.mkdir(exist_ok=True)
    return wd


def pin_server_working_dir(base_url: str, path, timeout: float = 10.0) -> bool:
    """Pin a spawned server's working directory. Returns True on success.

    WHY THIS EXISTS -- a spawned `ppxai-server` shares the developer's real
    `~/.ppxai/`, so it restores the most recent session, and sessions persist
    `working_dir` (EngineClient.set_working_dir writes it via
    session.set_working_dir). On a dev host that is routinely `$HOME`. Any
    endpoint that walks the working directory then walks the developer's home:
    `/files/tree` at depth 3 measured 12,523 dirs / 30,598 files / 2.7s warm
    against 0.06s for the repo -- enough to blow the smoke test's timeout under
    suite load, while passing on CI where HOME is empty. That produced two
    "flaky" failures whose real cause was inherited host state.

    This is the third time host-state inheritance has bitten this suite (see
    also the v1.19.0 retag: the release gate inherited ~/.ppxai provider config
    and diverged local-vs-CI). Pin it explicitly rather than hoping.

    Goes through POST /context/working_dir -> EngineClient.set_working_dir,
    the canonical choke point that also updates AppState, the session, the
    checkpoint manager, and emits WORKING_DIR_CHANGED -- so the server ends up
    in the same state a real client would produce.
    """
    import httpx

    try:
        r = httpx.post(
            f"{base_url}/context/working_dir",
            json={"path": str(path)},
            timeout=timeout,
        )
        return r.status_code < 400
    except Exception:
        # Non-fatal: the caller's assertions still hold, they are just
        # exposed to whatever directory the host handed the server.
        return False


# ---------------------------------------------------------------------------
# Test timing report.
#
# Every phase is counted -- setup, call AND teardown. The previous summary
# timed only `call`, and on 2026-09-27 73% of the Windows suite was fixture
# SETUP (a server start per `with TestClient(app)`), so a suite that tripled
# in length never showed a slow test. Collected in pytest_runtest_logreport,
# which xdist replays on the controller, so parallel runs report too.
#
# Each run is saved to .pytest_timings/last.json (gitignored) and compared
# with the previous one: a test that got much slower is listed by name.
# ---------------------------------------------------------------------------

_pytest_config = None  # set in pytest_configure; logreport gets no config
_TIMINGS_DIR = Path(__file__).resolve().parent.parent / ".pytest_timings"
_SLOWER_FACTOR = 2.0   # listed as a regression when this many times slower
_SLOWER_MIN_S = 1.0    # ... and at least this slow now (ignore noise)


def pytest_sessionstart(session):
    session.config._ppxai_session_t0 = time.perf_counter()


def pytest_runtest_logreport(report):
    durations = getattr(_pytest_config, "_test_durations", None) if _pytest_config else None
    if durations is None:
        return
    row = durations.setdefault(report.nodeid, {"setup": 0.0, "call": 0.0, "teardown": 0.0})
    row[report.when] += report.duration


def _write_timings(durations: dict) -> dict:
    """Save this run; return the previous run's {nodeid: total} (or {})."""
    previous = {}
    try:
        _TIMINGS_DIR.mkdir(exist_ok=True)
        last = _TIMINGS_DIR / "last.json"
        if last.exists():
            previous = json.loads(last.read_text(encoding="utf-8"))
            (_TIMINGS_DIR / "previous.json").write_text(
                json.dumps(previous), encoding="utf-8")
        last.write_text(json.dumps(
            {k: round(sum(v.values()), 4) for k, v in durations.items()}),
            encoding="utf-8")
    except (OSError, ValueError):
        pass
    return previous


def pytest_terminal_summary(terminalreporter: TerminalReporter, exitstatus, config):
    durations = getattr(config, "_test_durations", None)
    if not durations or hasattr(config, "workerinput"):  # xdist worker: controller reports
        return

    fake_home = getattr(config, "_ppxai_fake_home", None)
    if fake_home is not None:
        kept = " (kept)" if os.environ.get(_KEEP_HOME_ENV) else ""
        terminalreporter.write_line(
            f"\n🏠 HOME for this run: {fake_home}{kept} "
            f"— the real {REAL_PPXAI_HOME} was never writable (Item 78)."
        )

    w = terminalreporter.write_line
    terminalreporter.section("TEST TIMING SUMMARY (setup + call + teardown)", sep="=", blue=True)

    totals = {k: sum(v.values()) for k, v in durations.items()}
    phase = {p: sum(v[p] for v in durations.values()) for p in ("setup", "call", "teardown")}
    spent = sum(totals.values())
    wall = time.perf_counter() - getattr(config, "_ppxai_session_t0", time.perf_counter())
    w(f"Tests: {len(totals)}   wall: {wall:.0f}s   test time: {spent:.0f}s "
      f"(setup {phase['setup']:.0f}s / call {phase['call']:.0f}s / "
      f"teardown {phase['teardown']:.0f}s)")

    w("\nSlowest tests (total = setup + call + teardown):")
    for nodeid, total in sorted(totals.items(), key=lambda kv: kv[1], reverse=True)[:15]:
        d = durations[nodeid]
        w(f"  {total:7.2f}s  (setup {d['setup']:.2f} / call {d['call']:.2f} / "
          f"teardown {d['teardown']:.2f})  {nodeid}", red=total > 5, yellow=1 < total <= 5)

    by_file: dict[str, list[float]] = {}
    for nodeid, total in totals.items():
        by_file.setdefault(nodeid.split("::", 1)[0], []).append(total)
    w("\nSlowest files:")
    for path, ts in sorted(by_file.items(), key=lambda kv: sum(kv[1]), reverse=True)[:10]:
        w(f"  {sum(ts):7.1f}s  {len(ts):5d} tests  {sum(ts) / len(ts):6.3f}s avg  {path}")

    previous = _write_timings(durations)
    slower = sorted(
        ((k, previous[k], t) for k, t in totals.items()
         if k in previous and t >= _SLOWER_MIN_S
         and t >= _SLOWER_FACTOR * max(previous[k], 0.001)),
        key=lambda r: r[2] - r[1], reverse=True)
    if slower:
        w(f"\nSlower than the previous run (>= {_SLOWER_FACTOR:g}x and >= {_SLOWER_MIN_S:g}s):",
          red=True)
        for nodeid, before, now in slower[:15]:
            w(f"  {before:7.2f}s -> {now:7.2f}s  {nodeid}", red=True)
