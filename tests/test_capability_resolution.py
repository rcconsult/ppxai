"""Config layers over per-model capabilities (plan I2).

Resolution order — SPECIFICITY first, authorship second:

    1. providers.<p>.models.<m>.capabilities   config   (per model)
    2. provider code: per-model table                   (per model)
    3. providers.<p>.capabilities              config   (per provider)
    4. provider code: default_capabilities              (per provider)

The two config layers do NOT sit above both code layers; see
TestSpecificityBeatsAuthorship for why, and what broke when they did.

These tests drive the REAL config file through `find_config_file()` rather
than stubbing the block reader. That is deliberate: a per-model
`capabilities` block is silently discarded by `load_config()` (its
`_convert_models_format` keeps only id/name/description, verified
2026-08-15), which is the fifth time a config key has been eaten by a
whitelist on this project. A stubbed reader cannot see that class of bug.
"""

from __future__ import annotations

import json

import pytest

from ppxai.config import capabilities as capmod
from ppxai.engine.providers.openai_native import OpenAINativeProvider
from ppxai.engine.types import ProviderCapabilities


@pytest.fixture
def config_file(tmp_path, monkeypatch):
    """Write a real ppxai-config.json and point the loader at it."""

    def _write(providers):
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(
            json.dumps(
                {"version": "1", "default_provider": "p", "providers": providers}
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        return cfg

    return _write


def _provider(**extra):
    base = {
        "name": "P",
        "base_url": "https://example.invalid",
        "api_key_env": "K",
    }
    base.update(extra)
    return {"p": base}


class TestPrecedence:
    def test_nothing_configured_returns_empty(self, config_file):
        config_file(_provider())
        assert capmod.config_capability_overrides("p", "m1") == {}

    def test_provider_level_applies_to_every_model(self, config_file):
        config_file(_provider(capabilities={"native_tool_calling": True}))
        for model in ("m1", "m2", "anything"):
            got = capmod.config_capability_overrides("p", model)
            assert got == {"native_tool_calling": True}

    def test_model_level_overrides_provider_level(self, config_file):
        config_file(
            _provider(
                capabilities={"native_tool_calling": True},
                models={"m1": {"capabilities": {"native_tool_calling": False}}},
            )
        )
        assert capmod.config_capability_overrides("p", "m1") == {
            "native_tool_calling": False
        }
        # A sibling model still sees the provider-level statement.
        assert capmod.config_capability_overrides("p", "m2") == {
            "native_tool_calling": True
        }

    def test_model_level_merges_rather_than_replaces(self, config_file):
        """Stating one field per model must not silently clear the others."""
        config_file(
            _provider(
                capabilities={"native_tool_calling": True, "web_search": True},
                models={"m1": {"capabilities": {"native_tool_calling": False}}},
            )
        )
        got = capmod.config_capability_overrides("p", "m1")
        assert got == {"native_tool_calling": False, "web_search": True}

    def test_unknown_provider_yields_nothing(self, config_file):
        config_file(_provider(capabilities={"native_tool_calling": True}))
        assert capmod.config_capability_overrides("absent", "m1") == {}


class TestSpecificityBeatsAuthorship:
    """A provider-wide config statement must NOT outrank a shipped per-MODEL
    table. Layers 2 and 3 interleave: specificity wins before authorship.

    Found by running against the developer's real config, not by design.
    It carries `providers.openai.capabilities.native_tool_calling: true` —
    a restatement of the provider default, written long before per-model
    tables existed. Under a flat "all config above all code" ordering that
    silently re-enabled native tools for o4-mini and cancelled the
    benchmark-backed table (10.9% vs 62.5%). The I2 unit tests all passed
    while this was broken, because none of them combined a provider-level
    statement with a shipped per-model override.
    """

    def test_provider_wide_config_does_not_cancel_a_shipped_model_table(
        self, config_file
    ):
        config_file(_provider(capabilities={"native_tool_calling": True}))
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities_for_model("o4-mini").native_tool_calling is False, (
            "a provider-wide config statement overrode the shipped per-model "
            "table; specificity must win before authorship"
        )

    def test_model_level_config_still_wins(self, config_file):
        """The operator CAN override the table — by naming the model."""
        config_file(
            _provider(
                capabilities={"native_tool_calling": False},
                models={"o4-mini": {"capabilities": {"native_tool_calling": True}}},
            )
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities_for_model("o4-mini").native_tool_calling is True

    def test_apply_ignores_the_provider_level_layer(self, config_file):
        """`base` already carries the provider-level statement (it arrives via
        default_capabilities), so re-applying it here would let it leapfrog
        the shipped table."""
        config_file(_provider(capabilities={"native_tool_calling": True}))
        base = ProviderCapabilities(native_tool_calling=False)
        got = capmod.apply_capability_overrides(base, "p", "m1")
        assert got.native_tool_calling is False


class TestMalformedConfigIsIgnored:
    """A hand-edited config must degrade, never crash a request."""

    @pytest.mark.parametrize(
        "providers",
        [
            {"p": "not-a-dict"},
            {"p": {"capabilities": "not-a-dict"}},
            {"p": {"models": "not-a-dict"}},
            {"p": {"models": {"m1": "not-a-dict"}}},
            {"p": {"models": {"m1": {"capabilities": []}}}},
        ],
    )
    def test_shapes(self, config_file, providers):
        config_file(providers)
        assert capmod.config_capability_overrides("p", "m1") == {}

    def test_unreadable_config_yields_nothing(self, monkeypatch):
        def boom():
            raise RuntimeError("unreadable")

        monkeypatch.setattr(capmod, "find_config_file", boom)
        assert capmod.config_capability_overrides("p", "m1") == {}

    def test_unknown_keys_are_dropped(self, config_file):
        """Including the __comment convention the example config uses."""
        config_file(
            _provider(
                capabilities={
                    "native_tool_calling": True,
                    "__comment": "docs",
                    "telepathy": True,
                }
            )
        )
        assert capmod.config_capability_overrides("p", "m1") == {
            "native_tool_calling": True
        }

    def test_string_booleans_are_coerced(self, config_file):
        config_file(_provider(capabilities={"native_tool_calling": "false"}))
        assert capmod.config_capability_overrides("p", "m1") == {
            "native_tool_calling": False
        }


class TestApplyOverrides:
    def test_no_config_returns_the_same_object(self, config_file):
        """I2 must be a pure refactor where nothing is configured."""
        config_file(_provider())
        base = ProviderCapabilities(native_tool_calling=True)
        assert capmod.apply_capability_overrides(base, "p", "m1") is base

    def test_override_flips_only_the_stated_field(self, config_file):
        config_file(
            _provider(models={"m1": {"capabilities": {"native_tool_calling": False}}})
        )
        base = ProviderCapabilities(native_tool_calling=True, web_search=True)
        got = capmod.apply_capability_overrides(base, "p", "m1")
        assert got.native_tool_calling is False
        assert got.web_search is True  # untouched

    def test_capability_fields_match_the_dataclass(self):
        """A field listed here but absent from ProviderCapabilities would be
        silently unsettable; one present there but missing here would be
        un-overridable. Both are quiet failures, so pin the pairing."""
        import dataclasses

        actual = [f.name for f in dataclasses.fields(ProviderCapabilities)]
        assert list(capmod._CAPABILITY_FIELDS) == actual


class TestProviderIntegration:
    """The whole chain, through a real provider."""

    def test_config_overrides_a_shipped_per_model_table(self, config_file):
        """o4-mini ships prompt-based; an operator can turn it back on."""
        config_file(
            _provider(models={"o4-mini": {"capabilities": {"native_tool_calling": True}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.shipped_capabilities_for_model("o4-mini").native_tool_calling is False
        assert p.get_capabilities_for_model("o4-mini").native_tool_calling is True

    def test_config_can_disable_a_shipped_capability(self, config_file):
        config_file(
            _provider(models={"gpt-5.4": {"capabilities": {"native_tool_calling": False}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.shipped_capabilities_for_model("gpt-5.4").native_tool_calling is True
        assert p.get_capabilities_for_model("gpt-5.4").native_tool_calling is False

    def test_unconfigured_model_is_untouched(self, config_file):
        config_file(
            _provider(models={"o4-mini": {"capabilities": {"native_tool_calling": True}}})
        )
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities_for_model("gpt-5.2").native_tool_calling is True

    def test_shipped_table_survives_with_no_config(self, config_file):
        config_file(_provider())
        p = OpenAINativeProvider(api_key="sk-test", provider_id="p")
        assert p.get_capabilities_for_model("o4-mini").native_tool_calling is False
        assert p.get_capabilities_for_model("gpt-5.2").native_tool_calling is True


class TestSubclassesOverrideTheShippedHook:
    """The split exists so a subclass cannot bypass the config layers.

    A provider that overrode the PUBLIC accessor would silently drop them —
    the same "override bypasses the shared path" shape that made the
    per-model hook unreachable before I1.
    """

    def test_no_provider_overrides_the_public_accessor(self):
        import re
        from pathlib import Path

        providers = (
            Path(__file__).resolve().parents[1] / "ppxai" / "engine" / "providers"
        )
        offenders = [
            path.name
            for path in providers.glob("*.py")
            if path.name != "base.py"
            and re.search(r"\n    def get_capabilities_for_model\(", path.read_text(encoding="utf-8"))
        ]
        assert offenders == [], (
            f"{offenders} override get_capabilities_for_model(), which skips "
            "the operator config layers. Override "
            "shipped_capabilities_for_model() instead."
        )

    def test_base_public_accessor_calls_the_shipped_hook(self):
        seen = {}

        class _P(OpenAINativeProvider):
            def shipped_capabilities_for_model(self, model):
                seen["model"] = model
                return ProviderCapabilities(native_tool_calling=True)

        p = _P(api_key="sk-test", provider_id="p")
        p.get_capabilities_for_model("whatever")
        assert seen["model"] == "whatever"
