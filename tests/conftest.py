import os
from pathlib import Path

import pytest
from _pytest.terminal import TerminalReporter
from dotenv import load_dotenv

#: The config this repository SHIPS. The suite's verdicts are pinned to it.
REPO_CONFIG_FILE = Path(__file__).resolve().parent.parent / "ppxai-config.json"


def pytest_configure(config):
    """Configure pytest before test collection.

    This is the earliest hook that runs before any test modules are imported.
    We load user's .env here so SSL_VERIFY and other env vars are available
    when provider modules are imported.
    """
    config._test_durations = []

    # Load user's .ppxai/.env for integration tests that need SSL_VERIFY=false
    # This must happen before any ppxai modules are imported
    user_env_path = os.path.expanduser('~/.ppxai/.env')
    if os.path.exists(user_env_path):
        load_dotenv(dotenv_path=user_env_path, override=True)

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
    # ---------------------------------------------------------------
    if not os.environ.get("PPXAI_CONFIG_FILE") and REPO_CONFIG_FILE.exists():
        os.environ["PPXAI_CONFIG_FILE"] = str(REPO_CONFIG_FILE)

    # Initialize config system (v1.15.3: DAG-based init)
    from ppxai.config import initialize
    initialize()


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


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_makereport(item, call):
    outcome = yield
    report = outcome.get_result()

    if report.when == "call":
        item.config._test_durations.append({
            "nodeid": item.nodeid,
            "duration": report.duration,
            "outcome": report.outcome
        })

def pytest_terminal_summary(terminalreporter: TerminalReporter, exitstatus, config):
    durations = getattr(config, "_test_durations", [])
    if not durations:
        return

    terminalreporter.section("TEST TIMING SUMMARY", sep="=", blue=True)

    total_time = sum(d["duration"] for d in durations)
    avg_time = total_time / len(durations)

    slowest = sorted(durations, key=lambda x: x["duration"], reverse=True)

    terminalreporter.write_line(f"📊 Total Tests: {len(durations)}")
    terminalreporter.write_line(f"⏱️  Total Time Spent: {total_time:.4f}s")
    terminalreporter.write_line(f"📈 Average:        {avg_time:.4f}s")

    terminalreporter.write_line("\n🏎️  Top 5 SLOWEST tests:")
    for i, d in enumerate(slowest[:5], 1):
        color = "red" if d["duration"] > 0.5 else "yellow"
        terminalreporter.write_line(
            f"  {i}. {d['nodeid']} ({d['duration']:.4f}s)", **{color: True}
        )

    fastest = slowest[-1]
    terminalreporter.write_line(f"\n🐇 Fastest: {fastest['nodeid']} ({fastest['duration']:.4f}s)", green=True)
