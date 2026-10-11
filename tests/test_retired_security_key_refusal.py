"""A retired config key that held a security control refuses to start.

Debt Item 46, owner decision 2026-10-11. ADR 0010 moved
`tools.agent.sandbox` to `execution.task.sandbox` with no dual-read. Left at
the old path, the filesystem seal reverted to `enforcement: "off"` and the
`read_paths.deny` list (.env, .ssh, secrets) stopped applying, silently. Now
`config.initialize()` raises, and every entry point exits with the message
instead of a traceback.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

import ppxai.config as config
from ppxai.commands.doctor import ADR_0010_KEY_MOVES
from ppxai.config import ConfigStore, RetiredSecurityKeyError, check_retired_security_keys
from ppxai.config.execution import RETIRED_SECURITY_KEYS
from ppxai.server import http as server_http

OLD = {"tools": {"agent": {"sandbox": {"enforcement": "in_process"}}}}


def test_the_retired_sandbox_key_raises_and_names_the_move():
    with pytest.raises(RetiredSecurityKeyError) as exc:
        check_retired_security_keys(OLD, "/path/to/ppxai-config.json")
    message = str(exc.value)
    assert "/path/to/ppxai-config.json" in message
    assert "`tools.agent.sandbox`" in message
    assert "`execution.task.sandbox`" in message


def test_it_refuses_even_when_the_new_key_is_also_set():
    both = {**OLD, "execution": {"task": {"sandbox": {"enforcement": "off"}}}}
    with pytest.raises(RetiredSecurityKeyError):
        check_retired_security_keys(both)


@pytest.mark.parametrize("cfg", [
    {},
    {"tools": {"agent": {"zombie_threshold": 5}}},
    {"tools": {"agent": None}},
    {"execution": {"task": {"sandbox": {"enforcement": "in_process"}}}},
])
def test_configs_without_it_pass(cfg):
    check_retired_security_keys(cfg)


def test_behaviour_class_moves_do_not_refuse():
    """Only a security loss refuses; /doctor warns about the rest."""
    check_retired_security_keys({"tools": {"agent": {"task_tier_enabled": True}}})


def test_the_refusal_list_is_exactly_doctors_security_rows():
    security = {path: new for path, new, _cost, severity in ADR_0010_KEY_MOVES
                if severity == "security"}
    assert RETIRED_SECURITY_KEYS == security


def test_initialize_raises_on_the_loaded_config():
    store = ConfigStore.get_instance()
    saved = store.config
    store.set_for_testing(OLD)
    try:
        with patch.object(config, "_loader_initialize", return_value=False):
            with pytest.raises(RetiredSecurityKeyError):
                config.initialize()
    finally:
        store.set_for_testing(saved)


def test_the_server_entry_exits_with_the_message():
    error = RetiredSecurityKeyError("cfg: `tools.agent.sandbox` is no longer read")
    with patch.object(server_http, "initialize", side_effect=error):
        with pytest.raises(SystemExit) as exc:
            server_http._initialize_or_exit()
    assert "tools.agent.sandbox" in str(exc.value.code)
