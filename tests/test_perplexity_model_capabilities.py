"""Perplexity per-model tool calling, and the admission guard (plan I3).

Closes debt Item 43. Two halves:

* the per-model table — `sonar-pro` / `sonar-reasoning-pro` do native tool
  calling, `sonar` / `sonar-deep-research` do not; and
* an admission guard, because those two answer a `tools` array with HTTP
  400 rather than degrading. Falling back to prompt-based tool calling is
  what produced Item 43's refusals and confabulated tool results, so a
  tool-carrying run on such a model is refused before it is minted.

The matrix below was measured live against api.perplexity.ai (2026-08-13,
re-verified 2026-08-23), not read from documentation — the docs were wrong
about this twice.
"""

from __future__ import annotations

import json

import pytest

from ppxai.engine.providers.perplexity import (
    PERPLEXITY_NATIVE_TOOL_MODELS,
    PERPLEXITY_TOOL_REJECTING_MODELS,
    PerplexityProvider,
)
from ppxai.engine.task_authorizer import (
    TaskAuthorizationError,
    _reject_tool_incapable_model,
)

#: model -> does the live API accept a `tools` array?
MEASURED = {
    "sonar": False,               # 400 "Tool calling is not supported"
    "sonar-pro": True,            # 200, emits tool_calls
    "sonar-reasoning-pro": True,  # 200, emits tool_calls
    "sonar-deep-research": False, # 400 "Tool parameters must be a JSON object."
}


def _provider():
    return PerplexityProvider(api_key="k", base_url="https://api.perplexity.ai")


class TestTableMatchesMeasurement:
    @pytest.mark.parametrize("model,capable", sorted(MEASURED.items()))
    def test_shipped_table(self, model, capable):
        got = _provider().shipped_capabilities_for_model(model).native_tool_calling
        assert got is capable, (
            f"{model}: table says {got}, live API says {capable}"
        )

    def test_unknown_model_defaults_to_not_capable(self):
        """A model we have not measured must degrade, not 400 the user."""
        p = _provider()
        assert (
            p.shipped_capabilities_for_model("sonar-9-turbo").native_tool_calling
            is False
        )

    def test_model_id_is_matched_case_insensitively(self):
        p = _provider()
        assert p.shipped_capabilities_for_model("Sonar-Pro").native_tool_calling

    def test_other_capabilities_are_preserved(self):
        """Flipping native_tool_calling must not clear web_search/citations —
        Perplexity's whole value is the built-in search."""
        p = _provider()
        caps = p.shipped_capabilities_for_model("sonar-pro")
        assert caps.native_tool_calling is True
        assert caps.web_search is True
        assert caps.citations is True
        assert caps.streaming is True

    def test_the_two_sets_are_disjoint_and_complete(self):
        assert not (PERPLEXITY_NATIVE_TOOL_MODELS & PERPLEXITY_TOOL_REJECTING_MODELS)
        assert (
            PERPLEXITY_NATIVE_TOOL_MODELS | PERPLEXITY_TOOL_REJECTING_MODELS
        ) == set(MEASURED)

    def test_provider_default_stays_false(self):
        """The safe default: an unmeasured model degrades rather than 400s."""
        assert PerplexityProvider.default_capabilities.native_tool_calling is False


class TestProfileModeDoesNotShortCircuitTheTable:
    """The capability table only decides if the model PROFILE lets it.

    `chat.py:693` resolves the mode first: `mode="prompt_based"` sets
    use_native=False WITHOUT consulting provider capabilities. Both capable
    Sonar profiles shipped as "prompt_based" (correct when written), so the
    table alone left Item 43 wide open — measured before the fix:

        sonar-pro  profile.mode=prompt_based  caps.native=True  -> use_native=False

    That is the same "the override exists but nothing reads it" shape as
    plan finding F1. Pinned here because the two live in different modules
    and nothing else couples them.
    """

    @pytest.mark.parametrize("model", sorted(PERPLEXITY_NATIVE_TOOL_MODELS))
    def test_capable_models_are_not_pinned_to_prompt_based(self, model):
        from ppxai.engine.model_profiles import get_profile

        mode = get_profile(model).tool_calling.mode
        assert mode != "prompt_based", (
            f"{model} resolves native tool calling in the capability table, "
            f'but its profile pins mode="prompt_based", which chat.py checks '
            "FIRST — the table would never be consulted."
        )

    @pytest.mark.parametrize("model,capable", sorted(MEASURED.items()))
    def test_end_to_end_mode_resolution(self, model, capable):
        """Replicates chat.py's resolution: profile mode, then capability."""
        from ppxai.engine.model_profiles import get_profile

        mode = get_profile(model).tool_calling.mode
        caps = _provider().shipped_capabilities_for_model(model)
        if mode == "prompt_based":
            use_native = False
        else:  # "native" or "auto" both gate on the capability
            use_native = caps.native_tool_calling
        assert use_native is capable, (
            f"{model}: chain resolves use_native={use_native}, live API "
            f"says tool calling is {'supported' if capable else 'rejected'}"
        )


class TestChatActuallySendsTools:
    """The provider must SEND the tools array, not just resolve a capability.

    `perplexity.chat()` carried `# Note: tools parameter is ignored` and had
    no native path at all — so the capability table, the profile mode, and
    the send-path wiring from I1 were ALL inert here. Live-verified before
    the fix: sonar-pro produced 0 tool calls and refused in prose, despite
    every upstream layer resolving native=True.

    Third instance of the same shape this arc (F1 wiring, profile mode
    short-circuit, now this). Each layer looked right in isolation.
    """

    def _capture_kwargs(self, provider, monkeypatch):
        seen = {}

        def fake_create(**kw):
            seen.update(kw)
            raise RuntimeError("stop after capture")

        monkeypatch.setattr(
            provider.client.chat.completions, "create", fake_create
        )
        return seen

    @pytest.mark.parametrize("model", sorted(PERPLEXITY_NATIVE_TOOL_MODELS))
    def test_capable_models_get_a_tools_array(self, model, monkeypatch):
        import asyncio

        from ppxai.engine.types import Message

        p = _provider()
        seen = self._capture_kwargs(p, monkeypatch)
        tools = [{"type": "function", "function": {"name": "read_file"}}]

        async def run():
            async for _ in p.chat(
                [Message(role="user", content="hi")],
                model=model,
                stream=False,
                tools=tools,
            ):
                pass

        asyncio.run(run())
        assert seen.get("tools") == tools, (
            f"{model} resolves native tool calling but chat() sent "
            f"tools={seen.get('tools')!r} — the capability never reached the wire"
        )
        assert seen.get("tool_choice") == "auto"

    @pytest.mark.parametrize("model", sorted(PERPLEXITY_TOOL_REJECTING_MODELS))
    def test_incapable_models_get_no_tools_array(self, model, monkeypatch):
        """These answer a tools array with HTTP 400, so it must not be sent."""
        import asyncio

        from ppxai.engine.types import Message

        p = _provider()
        seen = self._capture_kwargs(p, monkeypatch)

        async def run():
            async for _ in p.chat(
                [Message(role="user", content="hi")],
                model=model,
                stream=False,
                tools=[{"type": "function", "function": {"name": "read_file"}}],
            ):
                pass

        asyncio.run(run())
        assert "tools" not in seen, (
            f"{model} rejects tool arrays with HTTP 400 but chat() sent one"
        )


class TestAdmissionGuard:
    """`sonar` HTTP-400s on tools; it must be refused, not fallen back."""

    @pytest.mark.parametrize("model", sorted(PERPLEXITY_TOOL_REJECTING_MODELS))
    def test_tool_run_on_an_incapable_model_is_refused(self, model):
        with pytest.raises(TaskAuthorizationError) as exc:
            _reject_tool_incapable_model("perplexity", model, ["read_file"])
        assert exc.value.status == 400
        assert model in exc.value.detail

    @pytest.mark.parametrize("model", sorted(PERPLEXITY_NATIVE_TOOL_MODELS))
    def test_tool_run_on_a_capable_model_is_allowed(self, model):
        _reject_tool_incapable_model("perplexity", model, ["read_file"])

    def test_a_toolless_run_is_always_allowed(self):
        """Plain chat on sonar is the common case and must not be blocked."""
        _reject_tool_incapable_model("perplexity", "sonar", [])

    def test_the_message_names_the_capable_models(self):
        """An error that does not say what to do instead is a dead end."""
        with pytest.raises(TaskAuthorizationError) as exc:
            _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])
        detail = exc.value.detail
        for model in PERPLEXITY_NATIVE_TOOL_MODELS:
            assert model in detail
        assert "Item 43" in detail  # so the reader can find the evidence

    def test_the_message_names_the_requested_tools(self):
        with pytest.raises(TaskAuthorizationError) as exc:
            _reject_tool_incapable_model("perplexity", "sonar", ["web_search"])
        assert "web_search" in exc.value.detail


class TestGuardIsReachedThroughAuthorize:
    """The guard must fire via the real admission path, not just directly.

    Every other test here calls `_reject_tool_incapable_model` itself, so
    all of them passed while the call site inside `authorize()` referenced
    an undefined `model_name` — a NameError that took out 46 tests in the
    full suite and none in this file. Unit-testing a helper does not test
    its wiring.
    """

    @pytest.mark.parametrize(
        "model,allowed", [("sonar", False), ("sonar-pro", True)]
    )
    def test_authorize_task_enforces_the_table(
        self, model, allowed, tmp_path, monkeypatch
    ):
        """Behavioural end-to-end through the real admission entry point.

        The structural check below proves the names bind; this proves the
        gate actually fires. Provider validation runs FIRST, so the API key
        must be present or the guard is never reached — which is itself why
        a naive version of this test would pass vacuously.
        """
        from ppxai.engine.task_authorizer import (
            TaskRequest,
            authorize_task,
        )

        monkeypatch.setenv("PERPLEXITY_API_KEY", "pplx-test-key")
        cfg = tmp_path / "ppxai-config.json"
        cfg.write_text(
            json.dumps(
                {
                    "version": "1",
                    "default_provider": "perplexity",
                    "providers": {
                        "perplexity": {
                            "name": "P",
                            "base_url": "https://api.perplexity.ai",
                            "api_key_env": "PERPLEXITY_API_KEY",
                            "default_model": "sonar-pro",
                            "models": {"sonar": {"name": "S"}, "sonar-pro": {"name": "SP"}},
                        }
                    },
                    "execution": {"task": {"enabled": True}},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))
        # The tool-capable tier ships default-OFF and its gate runs BEFORE
        # the capability guard, so without this the test would assert on the
        # wrong rejection. Patch the accessor, matching
        # test_task_authorization_parity.py.
        from ppxai.engine import task_authorizer as _authz

        monkeypatch.setattr(
            _authz,
            "_task_cfg",
            lambda: {
                "enabled": True,
                "sandbox": {},
                "consent": {},
                "budgets": {},
            },
        )

        req = TaskRequest(
            task="read the file",
            tools=["read_file"],
            spec=None,
            skills=[],
            profile=None,
            enrichment=None,
            provider="perplexity",
            model=model,
            system=None,
            budget=None,
            network=None,
            workdir=None,
        )
        if allowed:
            authorize_task(req)  # must not raise
        else:
            with pytest.raises(TaskAuthorizationError) as exc:
                authorize_task(req)
            assert "does not support tool calling" in exc.value.detail

    def test_the_call_site_uses_a_defined_variable(self):
        """Cheap structural proof that the wiring compiles and binds.

        A NameError inside a rarely-hit branch is invisible until that
        branch runs; compiling the module is not enough because the name is
        resolved at call time.
        """
        import inspect

        from ppxai.engine import task_authorizer as ta

        src = inspect.getsource(ta.authorize)
        assert "_reject_tool_incapable_model(" in src, (
            "authorize() no longer calls the capability guard — the table "
            "would stop being enforced at admission"
        )
        # The names passed must exist in the function's own scope.
        call = src.split("_reject_tool_incapable_model(", 1)[1].split(")", 1)[0]
        for arg in (a.strip() for a in call.split(",")):
            assert arg in src.replace(
                f"_reject_tool_incapable_model({call})", ""
            ), f"{arg!r} is passed to the guard but never bound in authorize()"


class TestGuardFailsOpenOnAnythingUnresolved:
    """This gate converts a KNOWN-bad combination into a clear error. It must
    never block one it merely failed to look up — a capability lookup is not
    a security boundary, and the real gates (shell reject, tier, egress) run
    regardless."""

    @pytest.mark.parametrize(
        "provider,model",
        [
            ("does-not-exist", "sonar"),
            ("perplexity", ""),
            ("", "sonar"),
            (None, "sonar"),
            ("perplexity", None),
        ],
    )
    def test_unresolvable_inputs_are_allowed(self, provider, model):
        _reject_tool_incapable_model(provider, model, ["read_file"])

    def test_a_raising_lookup_is_allowed(self, monkeypatch):
        import ppxai.engine.providers as provmod

        def boom(_name):
            raise RuntimeError("registry down")

        monkeypatch.setattr(provmod, "get_provider_class", boom)
        _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])

    def test_capable_providers_are_untouched(self):
        _reject_tool_incapable_model("openai", "gpt-5.4", ["read_file"])


class TestOperatorConfigWins:
    """Same precedence as everywhere else: an operator naming the model
    outranks the shipped table. The escape hatch if Perplexity changes a
    model's support before we ship a new table."""

    @pytest.fixture
    def config_file(self, tmp_path, monkeypatch):
        def _write(models):
            cfg = tmp_path / "ppxai-config.json"
            cfg.write_text(
                json.dumps(
                    {
                        "version": "1",
                        "default_provider": "perplexity",
                        "providers": {
                            "perplexity": {
                                "name": "P",
                                "base_url": "https://api.perplexity.ai",
                                "api_key_env": "PERPLEXITY_API_KEY",
                                "models": models,
                            }
                        },
                    }
                ),
                encoding="utf-8",
            )
            monkeypatch.setenv("PPXAI_CONFIG_FILE", str(cfg))

        return _write

    def test_operator_can_unblock_a_model_the_table_calls_incapable(
        self, config_file
    ):
        config_file({"sonar": {"capabilities": {"native_tool_calling": True}}})
        _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])

    def test_operator_can_block_a_model_the_table_calls_capable(
        self, config_file
    ):
        config_file({"sonar-pro": {"capabilities": {"native_tool_calling": False}}})
        with pytest.raises(TaskAuthorizationError):
            _reject_tool_incapable_model("perplexity", "sonar-pro", ["read_file"])
