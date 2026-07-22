"""Operator config for task-tier web_search (v1.19.1).

Three config knobs under `tools.web_search`, all read by the /task tier:

  * `preferred` pins the search backend AND narrows the AC-2 egress superset to
    that backend's host(s) (web_premium is held to it with no cross-backend
    fallback), so a perplexity-pinned pod authorizes web_search with only
    api.perplexity.ai in the allowlist.
  * `task_default_allow` pre-authorizes egress hosts so users don't retype
    `--allow` every run.
  * `enabled=false` bans web_search from the tool-capable tier.
"""

from __future__ import annotations

import os

import pytest

from ppxai.config.tools import ConfigStore
from ppxai.engine.tools import network_policy as np
from ppxai.server.routes import agent_v1


@pytest.fixture
def tools_cfg(monkeypatch):
    """Isolate tools.* config + web_search API-key env for one test."""
    cs = ConfigStore.get_instance()
    original = cs.config.get("tools")
    cs.config["tools"] = {}
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    try:
        yield cs.config["tools"]
    finally:
        if original is None:
            cs.config.pop("tools", None)
        else:
            cs.config["tools"] = original


# --- egress narrowing (network_policy) -------------------------------------

def test_auto_keeps_full_superset(tools_cfg):
    assert np.pinned_web_search_backend() is None
    assert np.tool_targets("web_search", {}) == np._WEB_SEARCH_ALL_HOSTS


def test_perplexity_pin_narrows_to_perplexity(tools_cfg, monkeypatch):
    tools_cfg["web_search"] = {"preferred": "perplexity"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    assert np.pinned_web_search_backend() == "perplexity"
    assert np.tool_targets("web_search", {}) == ["https://api.perplexity.ai/"]


def test_pin_without_key_falls_back_to_superset(tools_cfg):
    # Fail-safe: never narrow egress on a pin that can't take effect.
    tools_cfg["web_search"] = {"preferred": "perplexity"}  # no PERPLEXITY_API_KEY
    assert np.pinned_web_search_backend() is None
    assert np.tool_targets("web_search", {}) == np._WEB_SEARCH_ALL_HOSTS


def test_duckduckgo_pin_needs_no_key(tools_cfg):
    tools_cfg["web_search"] = {"preferred": "duckduckgo"}
    assert np.pinned_web_search_backend() == "duckduckgo"
    assert np.tool_targets("web_search", {}) == [
        "https://duckduckgo.com/", "https://html.duckduckgo.com/"
    ]


def test_authorize_perplexity_pin_allows_single_host_grant(tools_cfg, monkeypatch):
    tools_cfg["web_search"] = {"preferred": "perplexity"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    d = np.NetworkPolicy(["api.perplexity.ai"]).authorize("web_search", {})
    assert d.allowed is True
    assert d.approved_targets == ("api.perplexity.ai",)


def test_authorize_auto_still_needs_full_superset(tools_cfg):
    # Backward-compatible: the confused-deputy defense is unchanged in auto mode.
    d = np.NetworkPolicy(["api.perplexity.ai"]).authorize("web_search", {})
    assert d.allowed is False


# --- ban + default-allow (agent_v1 route helpers) --------------------------

def test_web_search_ban(tools_cfg):
    tools_cfg["web_search"] = {"enabled": False}
    assert agent_v1._web_search_banned(["web_search", "read_file"]) is True
    assert agent_v1._web_search_banned(["read_file"]) is False


def test_web_search_enabled_default_true(tools_cfg):
    tools_cfg["web_search"] = {}
    assert agent_v1._web_search_banned(["web_search"]) is False


def test_task_default_allow_merges_and_dedups(tools_cfg):
    tools_cfg["web_search"] = {"task_default_allow": ["api.perplexity.ai"]}
    assert agent_v1._with_task_default_allow([]) == ["api.perplexity.ai"]
    assert agent_v1._with_task_default_allow(["api.perplexity.ai", "x.com"]) == [
        "api.perplexity.ai", "x.com"
    ]


def test_task_default_allow_empty_is_noop(tools_cfg):
    tools_cfg["web_search"] = {}
    net = [{"host": "example.com"}]
    assert agent_v1._with_task_default_allow(net) == net


# --- no cross-backend fallback when pinned (web_premium) --------------------

def test_pinned_backend_does_not_fall_back(tools_cfg, monkeypatch):
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "perplexity"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")

    async def _boom(*a, **k):
        raise RuntimeError("perplexity down")

    def _ddg_must_not_run(*a, **k):
        raise AssertionError("DuckDuckGo fallback must NOT run when pinned")

    monkeypatch.setattr(web_premium, "web_search_perplexity", _boom)
    monkeypatch.setattr(web, "web_search", _ddg_must_not_run)

    out = asyncio.run(web_premium.web_search_premium("q"))
    assert "web_search error" in out
    assert "perplexity" in out
