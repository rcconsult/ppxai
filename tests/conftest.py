import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest
from _pytest.terminal import TerminalReporter
from dotenv import load_dotenv

#: The config this repository SHIPS. The suite's verdicts are pinned to it.
REPO_CONFIG_FILE = Path(__file__).resolve().parent.parent / "ppxai-config.json"

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
    real_web = REAL_PPXAI_HOME / "web"
    if real_web.is_dir():
        (ppxai_home / "web").symlink_to(real_web, target_is_directory=True)

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
    global FAKE_HOME

    config._test_durations = []

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
    # ---------------------------------------------------------------
    if not os.environ.get("PPXAI_CONFIG_FILE") and REPO_CONFIG_FILE.exists():
        os.environ["PPXAI_CONFIG_FILE"] = str(REPO_CONFIG_FILE)

    # Initialize config system (v1.15.3: DAG-based init)
    from ppxai.config import initialize
    initialize()

    # Item 78, second half: correct anything the redirect could not have
    # covered. Expected to rebind NOTHING (the fence in
    # tests/test_home_hermeticity.py asserts the real-home set is empty);
    # recorded on `config` so that fence can report what had to be fixed up.
    config._ppxai_rebound = rebind_home_derived_paths()


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

    fake_home = getattr(config, "_ppxai_fake_home", None)
    if fake_home is not None:
        kept = " (kept)" if os.environ.get(_KEEP_HOME_ENV) else ""
        terminalreporter.write_line(
            f"\n🏠 HOME for this run: {fake_home}{kept} "
            f"— the real {REAL_PPXAI_HOME} was never writable (Item 78)."
        )

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
