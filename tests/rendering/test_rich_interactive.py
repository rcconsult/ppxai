"""
Tests for RichRenderer interactive renderers: ConsentResult and PromptResult.

Covers:
- render_consent: numbered options, default selection, user_response stored
- render_prompt: free-form input, default value, validation loop, user_input stored
"""

from unittest.mock import patch

from ppxai.commands.results import ConsentResult, PromptResult, ResultStatus
from ppxai.rendering.rich_renderer import RichRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _render_consent(result: ConsentResult, user_choice: str) -> None:
    """Run render_consent with Prompt.ask mocked to return user_choice."""
    with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value=user_choice):
        RichRenderer.render(result)


def _render_prompt(result: PromptResult, user_inputs) -> None:
    """Run render_prompt with Prompt.ask mocked to iterate over user_inputs."""
    with patch("ppxai.rendering.rich_renderer.Prompt.ask", side_effect=user_inputs):
        RichRenderer.render(result)


# ---------------------------------------------------------------------------
# ConsentResult
# ---------------------------------------------------------------------------

class TestRenderConsent:
    """render_consent stores the chosen option in result.user_response."""

    def _make_consent(self, options=None, default=None):
        return ConsentResult(
            status=ResultStatus.INFO,
            message="Execute command?",
            question="This may modify files.",
            options=options or ["Allow", "Deny"],
            default=default or "Deny",
        )

    def test_allow_stored(self):
        result = self._make_consent()
        _render_consent(result, "1")  # "1" → "Allow"
        assert result.user_response == "Allow"

    def test_deny_stored(self):
        result = self._make_consent()
        _render_consent(result, "2")  # "2" → "Deny"
        assert result.user_response == "Deny"

    def test_three_option_middle(self):
        result = self._make_consent(
            options=["Allow", "Always Allow", "Deny"],
            default="Deny",
        )
        _render_consent(result, "2")
        assert result.user_response == "Always Allow"

    def test_three_option_last(self):
        result = self._make_consent(
            options=["Allow", "Always Allow", "Deny"],
            default="Deny",
        )
        _render_consent(result, "3")
        assert result.user_response == "Deny"

    def test_prompt_ask_receives_correct_choices(self):
        result = self._make_consent(options=["Yes", "No", "Skip"])
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="1") as mock_ask:
            RichRenderer.render(result)
        # choices kwarg must contain "1", "2", "3"
        _, kwargs = mock_ask.call_args
        assert set(kwargs["choices"]) == {"1", "2", "3"}

    def test_default_index_matches_default_option(self):
        result = self._make_consent(
            options=["Allow", "Deny", "Always Allow"],
            default="Deny",
        )
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="2") as mock_ask:
            RichRenderer.render(result)
        _, kwargs = mock_ask.call_args
        assert kwargs["default"] == "2"  # "Deny" is at index 1 → "2"

    def test_default_first_option_when_default_not_in_list(self):
        result = self._make_consent(options=["Allow", "Deny"], default="Unknown")
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="1") as mock_ask:
            RichRenderer.render(result)
        _, kwargs = mock_ask.call_args
        assert kwargs["default"] == "1"

    def test_context_displayed(self, capsys):
        result = ConsentResult(
            status=ResultStatus.INFO,
            message="Delete file?",
            question="",
            options=["Allow", "Deny"],
            default="Deny",
            context={"path": "/tmp/foo.py", "risk": "high"},
        )
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="1"):
            RichRenderer.render(result)
        # Context rendering happens on console (Rich), just verify no exception raised


# ---------------------------------------------------------------------------
# PromptResult
# ---------------------------------------------------------------------------

class TestRenderPrompt:
    """render_prompt stores the entered value in result.user_input."""

    def _make_prompt(self, validation=None, placeholder="", default=""):
        return PromptResult(
            status=ResultStatus.INFO,
            message="Session name required",
            prompt="Enter session name:",
            placeholder=placeholder,
            default=default,
            validation=validation,
        )

    def test_value_stored(self):
        result = self._make_prompt()
        _render_prompt(result, ["my-session"])
        assert result.user_input == "my-session"

    def test_empty_string_stored(self):
        result = self._make_prompt()
        _render_prompt(result, [""])
        assert result.user_input == ""

    def test_default_used(self):
        result = self._make_prompt(default="default-name")
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="default-name") as mock_ask:
            RichRenderer.render(result)
        _, kwargs = mock_ask.call_args
        assert kwargs["default"] == "default-name"

    def test_validation_pass_on_first_try(self):
        result = self._make_prompt(validation=r"^[a-z0-9-]+$")
        _render_prompt(result, ["valid-name"])
        assert result.user_input == "valid-name"

    def test_validation_retry_then_pass(self):
        """Invalid input is rejected; loop retries until valid."""
        result = self._make_prompt(validation=r"^[a-z0-9-]+$")
        _render_prompt(result, ["INVALID!!!", "valid-name"])
        assert result.user_input == "valid-name"

    def test_validation_multiple_retries(self):
        result = self._make_prompt(validation=r"^\d+$")
        _render_prompt(result, ["abc", "12x", "42"])
        assert result.user_input == "42"

    def test_no_validation_accepts_any_value(self):
        result = self._make_prompt(validation=None)
        _render_prompt(result, ["anything goes!"])
        assert result.user_input == "anything goes!"

    def test_empty_input_skips_validation(self):
        """Empty string bypasses regex validation (treated as 'no input')."""
        result = self._make_prompt(validation=r"^\d+$")
        _render_prompt(result, [""])
        assert result.user_input == ""

    def test_prompt_ask_called_once_on_valid(self):
        result = self._make_prompt(validation=r"^[a-z]+$")
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", return_value="hello") as mock_ask:
            RichRenderer.render(result)
        assert mock_ask.call_count == 1

    def test_prompt_ask_called_twice_on_one_retry(self):
        result = self._make_prompt(validation=r"^[a-z]+$")
        with patch("ppxai.rendering.rich_renderer.Prompt.ask", side_effect=["UPPER", "lower"]) as mock_ask:
            RichRenderer.render(result)
        assert mock_ask.call_count == 2
        assert result.user_input == "lower"
