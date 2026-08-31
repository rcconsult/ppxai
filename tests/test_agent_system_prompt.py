"""Agent-tier system-prompt seam (v1.19.x).

/v1/agent/task replaces the provider's CHAT system prompt with bounded-agent
framing (+ the caller's `system`, e.g. a rendered AGENT.md) so a tool-capable
run uses GRANTED tools instead of native fallbacks (the Perplexity
native-search substitution). The seam is a per-engine
`system_prompt_override` honored by engine.chat's prompt assembly.
"""

from __future__ import annotations

from ppxai.server.routes.agent_v1 import (
    DEFAULT_AGENT_SYSTEM_PROMPT,
    compose_agent_system_prompt,
)


class TestComposeAgentSystemPrompt:
    def test_default_when_no_caller_system(self):
        assert compose_agent_system_prompt(None) == DEFAULT_AGENT_SYSTEM_PROMPT
        assert compose_agent_system_prompt("") == DEFAULT_AGENT_SYSTEM_PROMPT
        assert compose_agent_system_prompt("   ") == DEFAULT_AGENT_SYSTEM_PROMPT

    def test_caller_system_composed_on_top_of_default(self):
        out = compose_agent_system_prompt("You are the Outlook agent. NEVER delete mail.")
        # base framing first, caller's refinement second
        assert out.startswith(DEFAULT_AGENT_SYSTEM_PROMPT)
        assert "NEVER delete mail" in out

    def test_default_forbids_native_fallback(self):
        # The whole point: tell the model NOT to substitute native capability
        # for a granted tool (the Perplexity web-search substitution).
        low = DEFAULT_AGENT_SYSTEM_PROMPT.lower()
        assert "only" in low and "granted" in low
        assert "native" in low  # "...do not fall back to any native capability..."


class TestEngineOverrideApplied:
    """The per-engine override REPLACES the config system prompt in chat
    assembly (both prompt-based and native paths read it)."""

    def test_override_attr_defaults_none(self):
        from ppxai.engine.client import EngineClient
        assert EngineClient().system_prompt_override is None

    def test_prompt_based_assembly_uses_override(self, monkeypatch):
        # _build_prompt_based_messages must prefer ctx.system_prompt_override
        # over get_system_prompt(provider). Use a minimal ctx double.
        import ppxai.engine.chat as chat_mod

        monkeypatch.setattr(chat_mod, "get_system_prompt", lambda p=None: "CONFIG-PROMPT")
        monkeypatch.setattr(chat_mod, "get_system_prompt_mode", lambda p=None: "prepend")

        class _ToolMgr:
            def get_tools_prompt(self, working_dir=None):
                return "TOOLS-BLOCK"
            def get_tool(self, name):
                return None

        class _Session:
            def get_messages(self):
                return []

        class _Ctx:
            provider_name = "perplexity"
            provider = None  # no native-search capability probe
            model = "sonar"
            tool_manager = _ToolMgr()
            session = _Session()
            system_prompt_override = "AGENT-FRAMING"
            def get_working_dir(self): return None
            def get_bootstrap_prompt(self): return ""

        msgs = chat_mod._build_prompt_based_messages(_Ctx())
        sys_msg = next(m for m in msgs if m.role == "system")
        assert "AGENT-FRAMING" in sys_msg.content
        assert "CONFIG-PROMPT" not in sys_msg.content   # override REPLACED it
        assert "TOOLS-BLOCK" in sys_msg.content          # tool block still present

    def test_prompt_based_assembly_falls_back_to_config(self, monkeypatch):
        # No override => config system prompt is used (unchanged behavior).
        import ppxai.engine.chat as chat_mod

        monkeypatch.setattr(chat_mod, "get_system_prompt", lambda p=None: "CONFIG-PROMPT")
        monkeypatch.setattr(chat_mod, "get_system_prompt_mode", lambda p=None: "prepend")

        class _ToolMgr:
            def get_tools_prompt(self, working_dir=None):
                return "TOOLS-BLOCK"
            def get_tool(self, name):
                return None

        class _Session:
            def get_messages(self):
                return []

        class _Ctx:
            provider_name = "perplexity"
            provider = None
            model = "sonar"
            tool_manager = _ToolMgr()
            session = _Session()
            system_prompt_override = None
            def get_working_dir(self): return None
            def get_bootstrap_prompt(self): return ""

        msgs = chat_mod._build_prompt_based_messages(_Ctx())
        sys_msg = next(m for m in msgs if m.role == "system")
        assert "CONFIG-PROMPT" in sys_msg.content


    def test_agent_override_suppresses_native_search_encouragement(self, monkeypatch):
        # The native-search-capability block ("you do NOT need a tool for
        # this") directly contradicts the agent framing and caused the
        # Perplexity substitution. With an override active it must be SUPPRESSED.
        import ppxai.engine.chat as chat_mod

        monkeypatch.setattr(chat_mod, "get_system_prompt", lambda p=None: "CFG")
        monkeypatch.setattr(chat_mod, "get_system_prompt_mode", lambda p=None: "prepend")

        class _Caps:
            citations = True
            web_search = True

        class _Provider:
            capabilities = _Caps()

        class _ToolMgr:
            def get_tools_prompt(self, working_dir=None):
                return "TOOLS-BLOCK"
            def get_tool(self, name):
                return None  # no web_search TOOL granted -> would trigger the block

        class _Session:
            def get_messages(self):
                return []

        def _ctx(override):
            class _C:
                provider_name = "perplexity"
                provider = _Provider()
                model = "sonar"
                tool_manager = _ToolMgr()
                session = _Session()
                system_prompt_override = override
                def get_working_dir(self): return None
                def get_bootstrap_prompt(self): return ""
            return _C()

        # WITHOUT override: native-search encouragement present (chat behavior).
        no_override = chat_mod._build_prompt_based_messages(_ctx(None))
        assert "Native Web Search Capability" in no_override[0].content
        # WITH agent override: suppressed.
        with_override = chat_mod._build_prompt_based_messages(_ctx("AGENT-FRAMING"))
        assert "Native Web Search Capability" not in with_override[0].content


class TestTaskThreadsSystem:
    """/v1/agent/task sets the override on its per-run engine via
    build_task_runner(system=...)."""

    def test_build_task_runner_accepts_system(self):
        import inspect

        from ppxai.server.routes.agent_v1 import build_task_runner
        assert "system" in inspect.signature(build_task_runner).parameters
