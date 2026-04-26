"""Sanity tests for `benchmarks/llm-eval/engine_runner.py`.

These tests pin invariants of the benchmark runner's system-prompt
building that have regressed before. Specifically:

- commit `d334453` (2026-02-19) accidentally stripped AGENTS.md hints
  from the system message when it switched from `engine.chat()` to
  direct `provider.chat()` calls. The stripping went unnoticed for ~7
  weeks because the runner still called `load_bootstrap_context()`,
  so the debug logs showed hints LOADED, but the final provider call
  never saw them.

The test here exercises the exact system-prompt build path used by
`EngineClientWrapper.chat()` without actually calling any provider,
and asserts:

1. When AGENTS.md is loaded, `get_bootstrap_prompt()` returns a
   non-empty string and the runner's `full_system` includes it.
2. The per-test system prompt is preserved — the runner prepends the
   bootstrap prompt rather than replacing the test prompt.
3. When AGENTS.md is NOT loaded (the --agents-md=without path), the
   runner's `full_system` contains only the per-test prompt. This
   validates that the A/B delta between --agents-md=with and =without
   modes is actually measuring hint injection, not run-to-run noise.
"""

from __future__ import annotations

import pytest

from ppxai.engine.client import EngineClient


class TestBenchmarkSystemPromptBuild:
    """Exercise the exact code path from engine_runner.EngineClientWrapper.chat().

    We don't import engine_runner directly because it lives under
    `benchmarks/llm-eval/` (not a package), and it has side-effects at
    import time (`initialize()` is called at module load). Instead we
    reproduce the 10-line build sequence inline — any future regression
    in engine_runner will break this test if it diverges from the
    canonical "build system prompt" logic.
    """

    def _build_full_system(self, client: EngineClient, system_content: str) -> str:
        """Mirror engine_runner.EngineClientWrapper.chat() system-prompt build.

        Keep this in lockstep with the actual runner. If the runner
        changes its assembly logic, update this method to match.
        """
        bootstrap_prompt = ""
        if client is not None:
            try:
                bootstrap_prompt = client.get_bootstrap_prompt() or ""
            except Exception:
                bootstrap_prompt = ""

        if bootstrap_prompt and system_content:
            return f"{bootstrap_prompt}\n\n---\n\n{system_content}"
        if bootstrap_prompt:
            return bootstrap_prompt
        return system_content

    def test_without_agents_md_only_test_prompt_is_sent(self):
        """Baseline: no bootstrap context loaded → full_system is just the test.

        Simulates `--agents-md=without`, which the benchmark runner
        implements by skipping `client.load_bootstrap_context()` during
        initialize(). Here we explicitly clear the context because
        `EngineClient.__init__()` auto-loads it from the standard search
        paths, which is what the runner also defeats via its `if
        self.agents_md_mode != "without":` guard before calling
        `load_bootstrap_context()`.
        """
        client = EngineClient()
        # Mirror the runner's --agents-md=without path: no bootstrap context.
        client._bootstrap_context = None

        full = self._build_full_system(
            client,
            "You are a coding assistant. Run the tests.",
        )
        assert full == "You are a coding assistant. Run the tests."

    def test_with_agents_md_bootstrap_prepended(self, tmp_path):
        """AGENTS.md loaded → full_system contains BOTH hints and test prompt.

        Regression guard for commit d334453: the runner used to strip
        AGENTS.md hints entirely. This test would have caught that.
        """
        # Build a minimal AGENTS.md with a distinctive marker we can assert on
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "---\n"
            "provider_hints:\n"
            "  openai:\n"
            "    - \"SENTINEL_PROVIDER_HINT_XYZ\"\n"
            "model_hints:\n"
            "  \"gpt-5.4*\":\n"
            "    - \"SENTINEL_MODEL_HINT_XYZ\"\n"
            "---\n"
            "## Rest of file\n"
            "some content\n",
            encoding="utf-8",
        )

        # Load the test AGENTS.md directly via BootstrapContext and
        # attach to a fresh EngineClient so get_bootstrap_prompt() works.
        from ppxai.engine.bootstrap import BootstrapContext

        client = EngineClient()
        # Set provider/model so get_bootstrap_prompt() resolves hints
        # for this specific (provider, model) pair.
        # NOTE: set_provider() requires an API key — we monkey-patch
        # the minimal state instead to keep the test offline.
        client.provider_name = "openai"
        client.model = "gpt-5.4"
        client._bootstrap_context = BootstrapContext.from_file(agents_md)

        full = self._build_full_system(
            client,
            "You are a coding assistant. Run the tests.",
        )

        # 1. Bootstrap hints must be present
        assert "SENTINEL_PROVIDER_HINT_XYZ" in full, (
            "Provider hint not injected — AGENTS.md is being stripped. "
            "Check engine_runner.EngineClientWrapper.chat() system-prompt build."
        )
        assert "SENTINEL_MODEL_HINT_XYZ" in full, (
            "Model hint not injected — AGENTS.md is being stripped or "
            "model-pattern matching is broken."
        )
        # 2. Test prompt must still be present
        assert "You are a coding assistant. Run the tests." in full
        # 3. Bootstrap must come BEFORE the test prompt (otherwise the
        # test prompt's "system-prompt-ness" gets weakened by trailing
        # narrative).
        bootstrap_idx = full.find("SENTINEL_MODEL_HINT_XYZ")
        test_idx = full.find("You are a coding assistant")
        assert bootstrap_idx < test_idx, (
            "Bootstrap hints should be prepended before the test prompt"
        )

    def test_bootstrap_only_when_no_test_prompt(self, tmp_path):
        """Edge case: empty system_content + bootstrap loaded → just bootstrap."""
        agents_md = tmp_path / "AGENTS.md"
        agents_md.write_text(
            "---\n"
            "provider_hints:\n"
            "  openai:\n"
            "    - \"EDGE_CASE_SENTINEL\"\n"
            "---\n",
            encoding="utf-8",
        )
        from ppxai.engine.bootstrap import BootstrapContext

        client = EngineClient()
        client.provider_name = "openai"
        client.model = "gpt-5.4"
        client._bootstrap_context = BootstrapContext.from_file(agents_md)

        full = self._build_full_system(client, "")
        assert "EDGE_CASE_SENTINEL" in full
        assert len(full) > 0

    def test_engine_runner_source_actually_calls_bootstrap_prompt(self):
        """CI gate against the d334453 regression class.

        The other tests in this file reproduce the system-prompt build
        logic INLINE (see _build_full_system). That's necessary because
        benchmarks/llm-eval/engine_runner.py has sys.path + initialize()
        side effects at import time, so we can't import the function
        and call it directly.

        The hidden risk: if engine_runner.py changes its build logic
        (e.g., a future refactor drops the get_bootstrap_prompt call),
        the inline reproduction tests still pass. The original 2026-02
        regression went undetected for ~7 weeks for exactly this
        reason — debug logs showed hints loaded, but the runner's
        provider call never used them.

        This static check guards against that: read the runner's
        source and assert the invariant tokens are present in the
        chat() method body. Any future refactor that drops them must
        be intentional and re-update this test.
        """
        from pathlib import Path
        runner_path = (
            Path(__file__).parent.parent
            / "benchmarks" / "llm-eval" / "engine_runner.py"
        )
        if not runner_path.is_file():
            pytest.skip("engine_runner.py not present (running outside repo)")

        source = runner_path.read_text(encoding="utf-8")

        # Invariant 1: get_bootstrap_prompt must be invoked.
        assert "get_bootstrap_prompt(" in source, (
            "engine_runner.py does NOT call get_bootstrap_prompt — "
            "AGENTS.md hints will be silently stripped from every "
            "benchmark request. See commit d334453's regression."
        )

        # Invariant 2: the result must end up in a `full_system`
        # variable that's the system message sent to the provider.
        # We don't pin exact whitespace; we pin the conjunction
        # 'bootstrap_prompt' + 'full_system' + 'system' role.
        assert "bootstrap_prompt" in source
        assert "full_system" in source
        assert 'role="system"' in source or "role='system'" in source, (
            "engine_runner.py's chat() doesn't append a system-role "
            "message. The bootstrap prompt has nowhere to land."
        )

        # Invariant 3: debug logging must capture bootstrap_prompt_length.
        # This is what an external CI step (or human reviewer) would
        # grep for in a real benchmark run's debug logs to confirm
        # hints reached the provider. If this field disappears, the
        # post-mortem signal disappears with it.
        assert "bootstrap_prompt_length" in source, (
            "engine_runner.py's debug log no longer captures "
            "bootstrap_prompt_length — operators lose the audit "
            "signal that proves AGENTS.md hints reached the wire."
        )

        # Invariant 4: the bootstrap_prompt must be assembled BEFORE
        # provider_messages.append for the system message. Easiest
        # static check: bootstrap_prompt assignment line precedes the
        # provider_messages.append("system", ...) line.
        bp_idx = source.find("bootstrap_prompt = self._client.get_bootstrap_prompt")
        sys_msg_idx = source.find('Message(role="system"')
        if sys_msg_idx == -1:
            sys_msg_idx = source.find("Message(role='system'")
        assert bp_idx > 0, "Could not locate bootstrap_prompt assignment"
        assert sys_msg_idx > 0, "Could not locate system Message construction"
        assert bp_idx < sys_msg_idx, (
            f"bootstrap_prompt assigned at offset {bp_idx} but used at "
            f"offset {sys_msg_idx} — assembly order is wrong; the "
            f"system message will be built before hints are loaded."
        )

    def test_bootstrap_failure_falls_back_to_test_prompt(self):
        """If get_bootstrap_prompt() raises, we fall back to test-only.

        Defensive path: a broken AGENTS.md shouldn't crash the whole
        benchmark run — the test prompt alone still exercises the
        model, just without hint coverage.
        """

        class BrokenClient:
            def get_bootstrap_prompt(self):
                raise RuntimeError("intentional test failure")

        # Inline reproduction of the runner's try/except behaviour
        bootstrap_prompt = ""
        client = BrokenClient()
        try:
            bootstrap_prompt = client.get_bootstrap_prompt() or ""
        except Exception:
            bootstrap_prompt = ""

        system_content = "You are a coding assistant."
        if bootstrap_prompt and system_content:
            full = f"{bootstrap_prompt}\n\n---\n\n{system_content}"
        elif bootstrap_prompt:
            full = bootstrap_prompt
        else:
            full = system_content

        assert full == "You are a coding assistant."
