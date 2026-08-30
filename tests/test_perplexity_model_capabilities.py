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
        got = _provider().get_facts_for_model(model).tool_mode != "prompt_based"
        assert got is capable, (
            f"{model}: table says {got}, live API says {capable}"
        )

    def test_unknown_model_defaults_to_not_capable(self):
        """A model we have not measured must degrade, not 400 the user."""
        p = _provider()
        assert p.get_facts_for_model("sonar-9-turbo").tool_mode == "prompt_based"

    def test_model_id_is_matched_case_insensitively(self):
        p = _provider()
        assert p.get_facts_for_model("Sonar-Pro").tool_mode != "prompt_based"

    def test_endpoint_abilities_are_untouched_by_tool_mode(self):
        """RETARGETED: this used to check that flipping the tool-calling
        boolean did not clear web_search/citations on the same record.

        Under ADR 0012 section 2 Q0e it cannot: they are on DIFFERENT
        records now, so no tool-mode resolution can reach them. That is a
        stronger guarantee than the original test asserted, and Perplexity's
        built-in search is its whole value, so the fence stays -- pointed at
        the endpoint record."""
        p = _provider()
        caps = p.get_capabilities()
        assert caps.web_search is True
        assert caps.citations is True
        assert caps.streaming is True
        assert p.get_facts_for_model("sonar-pro").tool_mode != "prompt_based"

    def test_the_measured_sets_still_agree_with_the_seed_rows(self):
        """The sets have no production readers; this keeps them honest.

        They record what was measured against the live API. The seed rows
        are what the router actually consults. If the two ever disagree,
        either the measurement is stale or a seed row is wrong -- and
        without this fence, nothing would say so.
        """
        p = _provider()
        for model in PERPLEXITY_NATIVE_TOOL_MODELS:
            assert p.get_facts_for_model(model).tool_mode != "prompt_based", (
                f"{model} was MEASURED tool-capable but its seed row "
                "resolves prompt_based"
            )
        for model in PERPLEXITY_TOOL_REJECTING_MODELS:
            assert p.get_facts_for_model(model).tool_mode == "prompt_based", (
                f"{model} REJECTS a tools array live, but its seed row "
                "resolves tool-capable"
            )

    def test_the_two_sets_are_disjoint_and_complete(self):
        assert not (PERPLEXITY_NATIVE_TOOL_MODELS & PERPLEXITY_TOOL_REJECTING_MODELS)
        assert (
            PERPLEXITY_NATIVE_TOOL_MODELS | PERPLEXITY_TOOL_REJECTING_MODELS
        ) == set(MEASURED)

    def test_the_provider_record_cannot_state_tool_mode(self):
        """RETARGETED from `test_provider_default_stays_false`.

        The safe default it guarded -- an unmeasured model degrades rather
        than 400s -- now lives on `ModelFacts` (asserted above). What
        replaces it here is the stronger structural claim: there is no
        provider-level tool-calling field left to get wrong, which is why a
        provider-wide statement can no longer speak for `sonar`."""
        assert not hasattr(
            PerplexityProvider.default_capabilities, "native_tool_calling"
        )


class TestOneLookupCannotShortCircuit:
    """Item 43's Layer-2 bug, fenced by REMOVING the second system.

    The original defect: `chat.py` resolved `profile.tool_calling.mode`
    FIRST and short-circuited on `prompt_based` without ever consulting
    provider capabilities. Both capable Sonar profiles shipped as
    `prompt_based` (correct when written), so the capability table alone
    left Item 43 wide open -- measured before the fix::

        sonar-pro  profile.mode=prompt_based  caps.native=True  -> False

    The predecessor of this class pinned the two systems into agreement,
    because they lived in different modules and nothing else coupled them.
    ADR 0012 section 2 Q0e deletes the coupling problem instead: there is
    ONE record, so "which system is asked first" has no referent. These
    tests now assert the single lookup matches the live API directly -- no
    chain to replicate, which is the whole improvement.
    """

    @pytest.mark.parametrize("model,capable", sorted(MEASURED.items()))
    def test_end_to_end_mode_resolution(self, model, capable):
        facts = _provider().get_facts_for_model(model)
        use_native = facts.tool_mode != "prompt_based"
        assert use_native is capable, (
            f"{model}: resolver says use_native={use_native}, live API "
            f"disagrees (capable={capable})"
        )

    def test_there_is_no_second_system_to_disagree_with(self):
        """The structural claim, asserted rather than assumed.

        If a second per-model tool-calling vocabulary ever comes back, this
        is where it gets caught: neither `ToolCallingProfile.mode` nor a
        provider-level boolean may reach the tool-mode decision.
        """
        import inspect

        from ppxai.engine.chat import chat_with_tools

        # Strip comments: the function's own docstring and comments explain
        # the defect by naming it, and matching those would make this fence
        # fire on its own explanation rather than on real code.
        src = "\n".join(
            line.split("#", 1)[0]
            for line in inspect.getsource(chat_with_tools).splitlines()
        )
        assert "tool_calling.mode" not in src
        assert "native_tool_calling" not in src



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
        config_file({"sonar": {"facts": {"tool_mode": "native"}}})
        _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])

    def test_operator_can_block_a_model_the_table_calls_capable(
        self, config_file
    ):
        config_file({"sonar-pro": {"facts": {"tool_mode": "prompt_based"}}})
        with pytest.raises(TaskAuthorizationError):
            _reject_tool_incapable_model("perplexity", "sonar-pro", ["read_file"])

    def test_the_legacy_block_no_longer_applies(self, config_file):
        """The clean break, asserted where it is most dangerous (Q0c).

        An operator whose config still says `capabilities.
        native_tool_calling: true` for `sonar` used to get a tool-capable
        run. Under the break that key resolves to nothing, so the guard
        refuses -- which is the SAFE direction, but silent, so `/doctor`
        must report it. That report is fenced in
        `tests/test_capability_resolution.py`.
        """
        config_file({"sonar": {"capabilities": {"native_tool_calling": True}}})
        with pytest.raises(TaskAuthorizationError):
            _reject_tool_incapable_model("perplexity", "sonar", ["read_file"])
