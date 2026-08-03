"""ADR 0009 step ④: the ONE shared web_search backend resolver (Q5 tuple).

Covers the ADR's "Requires" list for the step:
- the precedence MATRIX (provider-level / global-level / mixed / neither),
  asserting the selected backend, the strictness actually applied, and the
  enumerated egress set all come from the SAME scope;
- the previously-missing divergence case — a global preference plus a
  conflicting per-provider override — asserting the backend the chain
  contacts and the host set the allowlist enumerates agree;
- the keyless fail-safe (a preferred backend without its API key is no
  preference at all — never narrow egress on config that can't take effect);
- the dead-key rule (per-provider `strict` without per-provider `preferred`);
- the /doctor checks (ordering-not-pin upgrade note, dead strict key,
  strict-while-enriched).
"""

from __future__ import annotations

import pytest

import ppxai.config as config_pkg
from ppxai.engine.tools.search_backends import (
    ALL_HOSTS,
    BACKEND_HOSTS,
    resolve_web_search_backend,
)


@pytest.fixture
def cfg(monkeypatch):
    """Pin the two config reads the resolver makes; keys cleared."""
    state = {"global": {}, "providers": {}}
    monkeypatch.setattr(
        config_pkg, "get_tool_config",
        lambda tool: dict(state["global"]) if tool == "web_search" else {},
    )
    monkeypatch.setattr(
        config_pkg, "get_provider_config",
        lambda name: {"web_search": dict(state["providers"].get(name, {}))},
    )
    monkeypatch.delenv("PERPLEXITY_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    return state


def _keys(monkeypatch, *envs):
    for e in envs:
        monkeypatch.setenv(e, "k")


# ---------------------------------------------------------------------------
# Precedence matrix — scope selected once, both fields read from it
# ---------------------------------------------------------------------------


class TestScopedTupleMatrix:
    def test_neither_states_defaults(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY", "GEMINI_API_KEY")
        res = resolve_web_search_backend("prov")
        assert res.scope == "default"
        assert res.preferred == "auto" and res.strict is False
        assert res.candidates == ("perplexity", "gemini", "duckduckgo")
        assert list(res.egress_hosts) == ALL_HOSTS

    def test_global_ordering_no_strict(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY", "GEMINI_API_KEY")
        cfg["global"] = {"preferred": "gemini"}
        res = resolve_web_search_backend(None)
        assert res.scope == "global"
        assert res.preferred == "gemini" and res.strict is False
        # Ordering: first choice, then the rest of the usable chain.
        assert res.candidates == ("gemini", "perplexity", "duckduckgo")
        assert list(res.egress_hosts) == ALL_HOSTS  # no narrowing w/o strict

    def test_global_strict_pins_and_narrows(self, cfg, monkeypatch):
        _keys(monkeypatch, "GEMINI_API_KEY")
        cfg["global"] = {"preferred": "gemini", "strict": True}
        res = resolve_web_search_backend(None)
        assert res.scope == "global"
        assert res.strict is True
        assert res.candidates == ("gemini",)
        assert list(res.egress_hosts) == BACKEND_HOSTS["gemini"]

    def test_provider_scope_owns_both_fields(self, cfg, monkeypatch):
        # Mixed: global states gemini+strict; the provider block states
        # preferred=perplexity WITHOUT strict. The provider block owns the
        # tuple, so strict is FALSE (its own default) — a per-provider
        # preference must never inherit a global strict it wasn't written
        # with (Problem 4 one layer up; the tuple rule forecloses it).
        _keys(monkeypatch, "PERPLEXITY_API_KEY", "GEMINI_API_KEY")
        cfg["global"] = {"preferred": "gemini", "strict": True}
        cfg["providers"]["prov"] = {"preferred": "perplexity"}
        res = resolve_web_search_backend("prov")
        assert res.scope == "provider:prov"
        assert res.preferred == "perplexity" and res.strict is False
        assert res.candidates[0] == "perplexity"
        assert list(res.egress_hosts) == ALL_HOSTS

    def test_provider_strict_with_provider_preferred(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY")
        cfg["providers"]["prov"] = {"preferred": "perplexity", "strict": True}
        res = resolve_web_search_backend("prov")
        assert res.scope == "provider:prov"
        assert res.strict is True
        assert list(res.egress_hosts) == BACKEND_HOSTS["perplexity"]

    def test_provider_strict_without_preferred_is_dead_key(self, cfg, monkeypatch):
        # Q5: out of scope by construction — global governs, warning raised.
        _keys(monkeypatch, "GEMINI_API_KEY")
        cfg["global"] = {"preferred": "gemini"}
        cfg["providers"]["prov"] = {"strict": True}
        res = resolve_web_search_backend("prov")
        assert res.scope == "global"
        assert res.strict is False
        assert any("dead key" in w for w in res.warnings)

    def test_keyless_preferred_fail_safe(self, cfg):
        # No PERPLEXITY_API_KEY: the preference (and its strict) is ignored
        # entirely — never narrow egress on config that can't take effect.
        cfg["global"] = {"preferred": "perplexity", "strict": True}
        res = resolve_web_search_backend(None)
        assert res.preferred == "auto" and res.strict is False
        assert list(res.egress_hosts) == ALL_HOSTS
        assert any("fail-safe" in w for w in res.warnings)

    def test_unknown_backend_name_warns_and_autos(self, cfg):
        cfg["global"] = {"preferred": "bing"}
        res = resolve_web_search_backend(None)
        assert res.preferred == "auto"
        assert any("unknown web_search backend" in w for w in res.warnings)


# ---------------------------------------------------------------------------
# The divergence case — both consumers read one answer
# ---------------------------------------------------------------------------


class TestConsumersAgree:
    def test_global_pref_with_conflicting_provider_override(self, cfg, monkeypatch):
        """The ADR's named missing test: global preference + conflicting
        per-provider override. Pre-④ the call-time resolver picked gemini
        while the egress set narrowed to perplexity (allowlist bypass /
        false deny, depending on the run's allow_outbound). Now the chain's
        first backend and the enumerated egress come from one resolution."""
        from ppxai.engine.tools import network_policy as np
        from ppxai.engine.tools.builtin import web_premium

        _keys(monkeypatch, "PERPLEXITY_API_KEY", "GEMINI_API_KEY")
        cfg["global"] = {"preferred": "perplexity", "strict": True}
        cfg["providers"]["prov"] = {"preferred": "gemini", "strict": True}

        # Call-time consumer:
        assert web_premium.get_premium_search_provider("prov") == "gemini"
        # Egress consumer, with the SAME provider context threaded:
        assert np.tool_targets("web_search", {}, provider_name="prov") == (
            BACKEND_HOSTS["gemini"]
        )
        # And a policy carrying the context authorizes with just that host.
        d = np.NetworkPolicy(
            ["generativelanguage.googleapis.com"], provider_name="prov"
        ).authorize("web_search", {})
        assert d.allowed is True

    def test_no_context_falls_back_to_global_scope(self, cfg, monkeypatch):
        from ppxai.engine.tools import network_policy as np

        _keys(monkeypatch, "PERPLEXITY_API_KEY")
        cfg["global"] = {"preferred": "perplexity", "strict": True}
        cfg["providers"]["prov"] = {"preferred": "gemini"}
        assert np.tool_targets("web_search", {}) == BACKEND_HOSTS["perplexity"]

    def test_get_premium_search_provider_contract_preserved(self, cfg, monkeypatch):
        from ppxai.engine.tools.builtin import web_premium

        # duckduckgo-first → None (free search), as before.
        cfg["global"] = {"preferred": "duckduckgo"}
        assert web_premium.get_premium_search_provider(None) is None
        # auto + only gemini keyed → gemini.
        cfg["global"] = {}
        _keys(monkeypatch, "GEMINI_API_KEY")
        assert web_premium.get_premium_search_provider(None) == "gemini"


# ---------------------------------------------------------------------------
# Loader passthrough — the step-④ live-trial catch
# ---------------------------------------------------------------------------


class TestLoaderPassthrough:
    def test_provider_web_search_block_survives_load(self, tmp_path, monkeypatch):
        """The loader's per-provider whitelist silently DROPPED the
        `web_search` block, so the per-provider `preferred` override
        (documented since v1.13.4) was dead config for every file-loaded
        provider — caught live in the step-④ trial (same hazard class as
        the F2 top-level `execution` whitelist gap)."""
        import json as _json

        from ppxai.config.loader import load_config

        cfg = {
            "version": "1.0",
            "default_provider": "test",
            "providers": {"test": {
                "name": "T", "base_url": "https://api.test/v1",
                "api_key_env": "TEST_KEY",
                "models": {"m1": {"name": "M1", "description": "d"}},
                "web_search": {"preferred": "perplexity", "strict": True},
            }},
        }
        p = tmp_path / "cfg.json"
        p.write_text(_json.dumps(cfg), encoding="utf-8")
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(p))
        loaded = load_config()
        assert loaded["providers"]["test"]["web_search"] == {
            "preferred": "perplexity", "strict": True,
        }


# ---------------------------------------------------------------------------
# /doctor checks
# ---------------------------------------------------------------------------


class TestDoctorChecks:
    def _section(self, monkeypatch, cfg_state, providers=("prov",),
                 run_web_search=False, profiles=None):
        from ppxai.commands import doctor as doctor_mod

        monkeypatch.setattr(
            config_pkg, "get_available_providers", lambda: list(providers)
        )
        from ppxai.config import execution as exec_mod
        monkeypatch.setattr(
            exec_mod, "get_execution_run_config",
            lambda: {"web_search": run_web_search, "grounding": False},
        )
        monkeypatch.setattr(
            exec_mod, "get_execution_profiles", lambda: profiles or {}
        )
        return "\n".join(doctor_mod._format_web_search_backend_section())

    def test_flags_preferred_without_strict(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY")
        cfg["global"] = {"preferred": "perplexity"}
        out = self._section(monkeypatch, cfg)
        assert "without strict" in out and "ORDERS the chain" in out

    def test_flags_dead_provider_strict(self, cfg, monkeypatch):
        cfg["providers"]["prov"] = {"strict": True}
        out = self._section(monkeypatch, cfg)
        assert "dead key" in out

    def test_flags_strict_plus_enrichment(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY")
        cfg["global"] = {"preferred": "perplexity", "strict": True}
        out = self._section(
            monkeypatch, cfg,
            profiles={"research": {"enrichment": True}},
        )
        assert "strict:true + enrichment" in out
        assert "execution.profiles.research" in out

    def test_clean_config_no_hazards(self, cfg, monkeypatch):
        _keys(monkeypatch, "PERPLEXITY_API_KEY")
        out = self._section(monkeypatch, cfg)
        assert "no preferred/strict config hazards" in out
