"""Unit tests for ppxai.prompts module."""
import pytest
from ppxai.prompts import CODING_PROMPTS, SPEC_GUIDELINES, SPEC_TEMPLATES


class TestCodingPrompts:
    """Tests for coding prompts."""

    def test_all_prompts_exist(self):
        """Test that all expected prompts exist."""
        expected_prompts = ["generate", "test", "docs", "implement", "debug", "explain", "convert"]
        for prompt_name in expected_prompts:
            assert prompt_name in CODING_PROMPTS, f"Missing prompt: {prompt_name}"

    def test_prompts_are_non_empty(self):
        """Test that all prompts have content."""
        for name, prompt in CODING_PROMPTS.items():
            assert isinstance(prompt, str), f"Prompt {name} is not a string"
            assert len(prompt) > 50, f"Prompt {name} seems too short"

    def test_prompts_contain_guidelines(self):
        """Test that prompts contain guidelines."""
        for name, prompt in CODING_PROMPTS.items():
            # Each prompt should have some form of guidelines
            assert "Follow" in prompt or "guidelines" in prompt.lower() or "-" in prompt, \
                f"Prompt {name} may be missing guidelines"


class TestSpecGuidelines:
    """Tests for specification guidelines."""

    def test_spec_guidelines_exist(self):
        """Test that spec guidelines exist."""
        assert SPEC_GUIDELINES is not None
        assert len(SPEC_GUIDELINES) > 100

    def test_spec_guidelines_has_sections(self):
        """Test that spec guidelines has expected sections."""
        assert "Overview" in SPEC_GUIDELINES
        assert "Requirements" in SPEC_GUIDELINES
        assert "Examples" in SPEC_GUIDELINES


class TestSpecTemplates:
    """Tests for specification templates."""

    def test_all_templates_exist(self):
        """Test that all expected templates exist."""
        expected_templates = ["api", "cli", "lib", "algo", "ui"]
        for template_name in expected_templates:
            assert template_name in SPEC_TEMPLATES, f"Missing template: {template_name}"

    def test_templates_are_non_empty(self):
        """Test that all templates have content."""
        for name, template in SPEC_TEMPLATES.items():
            assert isinstance(template, str), f"Template {name} is not a string"
            assert len(template) > 100, f"Template {name} seems too short"

    def test_api_template_has_required_sections(self):
        """Test that API template has required sections."""
        api_template = SPEC_TEMPLATES["api"]
        assert "Endpoint" in api_template
        assert "Request" in api_template
        assert "Response" in api_template

    def test_cli_template_has_required_sections(self):
        """Test that CLI template has required sections."""
        cli_template = SPEC_TEMPLATES["cli"]
        assert "Command" in cli_template
        assert "Options" in cli_template
        assert "Examples" in cli_template
