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


# --- get_weather premium backend policy (v1.19.1) -------------------------

def test_get_weather_targets_auto_no_key(tools_cfg):
    tools_cfg["web_search"] = {"preferred": "auto"}
    # wttr.in + Open-Meteo (both key-free) are always in the superset.
    assert np.tool_targets("get_weather", {}) == [
        "https://wttr.in/", "http://wttr.in/",
        "https://api.open-meteo.com/", "https://geocoding-api.open-meteo.com/",
    ]


def test_get_weather_targets_auto_with_perplexity_key(tools_cfg, monkeypatch):
    # Auto mode can fall back to premium, so its egress superset must include it.
    tools_cfg["web_search"] = {"preferred": "auto"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    assert np.tool_targets("get_weather", {}) == [
        "https://wttr.in/", "http://wttr.in/",
        "https://api.open-meteo.com/", "https://geocoding-api.open-meteo.com/",
        "https://api.perplexity.ai/",
    ]


def test_get_weather_pinning_does_not_divert_weather(tools_cfg, monkeypatch):
    # `preferred` governs SEARCH, not weather — wttr.in stays the preferred
    # (accurate) weather source, so its target set is NOT narrowed by pinning.
    tools_cfg["web_search"] = {"preferred": "perplexity"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")
    assert np.tool_targets("get_weather", {}) == [
        "https://wttr.in/", "http://wttr.in/",
        "https://api.open-meteo.com/", "https://geocoding-api.open-meteo.com/",
        "https://api.perplexity.ai/",
    ]


def test_get_weather_tries_wttr_first_even_when_pinned(tools_cfg, monkeypatch):
    # Even with a premium backend pinned for search, weather tries wttr.in FIRST
    # (accuracy) — premium is only a fallback if wttr.in fails.
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "perplexity"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")

    def _premium_must_not_run(*a, **k):
        raise AssertionError("premium must NOT run when wttr.in succeeds")

    monkeypatch.setattr(web_premium, "web_search_premium", _premium_must_not_run)
    monkeypatch.setattr(web, "get_weather", lambda loc, fmt="short": "Weather for Ornex:\n+30C")

    out = asyncio.run(web_premium.get_weather_premium("Ornex"))
    assert "Weather for Ornex" in out


def test_get_weather_uses_openmeteo_before_premium(tools_cfg, monkeypatch):
    # Tier 2: when wttr.in fails, Open-Meteo (reliable, key-free) is tried
    # BEFORE any premium web search — premium must NOT run if open-meteo works.
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "auto"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")

    def _premium_must_not_run(*a, **k):
        raise AssertionError("premium must NOT run when open-meteo succeeds")

    monkeypatch.setattr(web_premium, "web_search_premium", _premium_must_not_run)
    monkeypatch.setattr(
        web, "get_weather",
        lambda loc, fmt="short": "Error: Could not connect to weather service. timed out",
    )
    monkeypatch.setattr(
        web, "get_weather_openmeteo",
        lambda loc, fmt="short": "Weather for Ornex (via open-meteo):\n☀️ Clear sky, 28.1°C",
    )

    out = asyncio.run(web_premium.get_weather_premium("Ornex"))
    assert "open-meteo" in out
    assert "28.1" in out


def test_get_weather_auto_falls_back_when_wttr_and_openmeteo_unreachable(
    tools_cfg, monkeypatch
):
    # Tier 3 (last resort): only when BOTH wttr.in AND Open-Meteo fail does the
    # premium web-search backend run.
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "auto"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")

    async def _fake_search(query, num=5, _provider_name=None):
        return "[via perplexity]\n\nSunny 25C"

    monkeypatch.setattr(web_premium, "web_search_premium", _fake_search)
    monkeypatch.setattr(
        web, "get_weather",
        lambda loc, fmt="short": "Error: Could not connect to weather service. timed out",
    )
    monkeypatch.setattr(
        web, "get_weather_openmeteo",
        lambda loc, fmt="short": "Error: Could not connect to open-meteo. timed out",
    )

    out = asyncio.run(web_premium.get_weather_premium("Ornex"))
    assert "perplexity" in out


def test_get_weather_no_key_returns_openmeteo_error(tools_cfg, monkeypatch):
    # Keyless host: both direct sources fail, no premium fallback → the more
    # informative open-meteo error is surfaced (not a hard crash).
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "auto"}  # no PERPLEXITY/GEMINI key

    monkeypatch.setattr(
        web, "get_weather",
        lambda loc, fmt="short": "Error: wttr down",
    )
    monkeypatch.setattr(
        web, "get_weather_openmeteo",
        lambda loc, fmt="short": "Error: Location 'Xyz' not found via open-meteo.",
    )

    out = asyncio.run(web_premium.get_weather_premium("Xyz"))
    assert "open-meteo" in out
    assert out.lstrip().startswith("Error")


# --- Open-Meteo backend formatting (web.get_weather_openmeteo) --------------

def _openmeteo_stub(geo, forecast):
    """Return a fake _openmeteo_get routing geocoding vs forecast by URL."""
    def _fake(base, params, timeout):
        return geo if "geocoding" in base else forecast
    return _fake


def test_openmeteo_formats_current(monkeypatch):
    from ppxai.engine.tools.builtin import web

    geo = {"results": [{"name": "Geneva", "admin1": "Geneva",
                        "country": "Switzerland", "latitude": 46.2, "longitude": 6.15}]}
    forecast = {"current": {"weather_code": 0, "temperature_2m": 28.1,
                            "apparent_temperature": 26.6, "relative_humidity_2m": 45,
                            "wind_speed_10m": 6.1}}
    monkeypatch.setattr(web, "_openmeteo_get", _openmeteo_stub(geo, forecast))

    out = web.get_weather_openmeteo("Geneva")
    assert "Geneva, Geneva, Switzerland" in out
    assert "open-meteo" in out
    assert "Clear sky" in out
    assert "28.1°C" in out
    assert "feels 26.6°C" in out
    assert "wind 6.1 km/h" in out


def test_openmeteo_forecast_includes_daily(monkeypatch):
    from ppxai.engine.tools.builtin import web

    geo = {"results": [{"name": "Geneva", "country": "Switzerland",
                        "latitude": 46.2, "longitude": 6.15}]}
    forecast = {
        "current": {"weather_code": 3, "temperature_2m": 20.0},
        "daily": {
            "time": ["2026-07-22", "2026-07-23"],
            "weather_code": [61, 0],
            "temperature_2m_max": [24.0, 29.0],
            "temperature_2m_min": [15.0, 17.0],
            "precipitation_probability_max": [80, 10],
        },
    }
    monkeypatch.setattr(web, "_openmeteo_get", _openmeteo_stub(geo, forecast))

    out = web.get_weather_openmeteo("Geneva", format="forecast")
    assert "2026-07-22" in out and "2026-07-23" in out
    assert "Slight rain" in out
    assert "15.0–24.0°C" in out
    assert "precip 80%" in out


def test_openmeteo_location_not_found(monkeypatch):
    from ppxai.engine.tools.builtin import web

    monkeypatch.setattr(web, "_openmeteo_get", _openmeteo_stub({"results": []}, {}))
    out = web.get_weather_openmeteo("Nowhereville")
    assert out.startswith("Error")
    assert "not found" in out


def test_openmeteo_network_error_is_stringified(monkeypatch):
    import urllib.error

    from ppxai.engine.tools.builtin import web

    def _boom(base, params, timeout):
        raise urllib.error.URLError("timed out")

    monkeypatch.setattr(web, "_openmeteo_get", _boom)
    out = web.get_weather_openmeteo("Geneva")
    assert out.startswith("Error")
    assert "open-meteo" in out


def test_get_weather_auto_uses_wttr_when_reachable(tools_cfg, monkeypatch):
    import asyncio

    from ppxai.engine.tools.builtin import web_premium, web

    tools_cfg["web_search"] = {"preferred": "auto"}
    monkeypatch.setenv("PERPLEXITY_API_KEY", "k")

    def _premium_must_not_run(*a, **k):
        raise AssertionError("premium must NOT run when wttr.in succeeds")

    monkeypatch.setattr(web_premium, "web_search_premium", _premium_must_not_run)
    monkeypatch.setattr(web, "get_weather", lambda loc, fmt="short": "Weather for Ornex:\n+18C")

    out = asyncio.run(web_premium.get_weather_premium("Ornex"))
    assert "Weather for Ornex" in out
