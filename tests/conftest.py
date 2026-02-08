import os
import pytest
from _pytest.terminal import TerminalReporter
from dotenv import load_dotenv


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

    # Initialize config system (v1.15.3: DAG-based init)
    from ppxai.config import initialize
    initialize()


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
