"""Tests for constants module - enum behavior and validation helpers."""

import pytest

from ppxai.constants import (
    ProviderName,
    MessageRole,
    ConsentMode,
    ConsentResponse,
    ConsentDecision,
    SystemPromptMode,
    ShellRiskLevel,
    FileEncoding,
    CheckpointBackend,
    is_valid_provider,
    is_valid_role,
    is_valid_consent_mode,
    is_valid_consent_response,
    is_valid_consent_decision,
    is_valid_prompt_mode,
    is_valid_risk_level,
    is_valid_encoding,
    is_valid_checkpoint_backend,
    is_valid_enum,
    get_enum_values,
)


class TestStrEnumBehavior:
    """Test that str, Enum classes behave correctly."""

    def test_provider_name_string_comparison(self):
        """Enum values should compare equal to their string values."""
        assert ProviderName.PERPLEXITY == "perplexity"
        assert ProviderName.GEMINI == "gemini"
        assert "openai" == ProviderName.OPENAI

    def test_message_role_in_dict(self):
        """Enum values should work as dict keys and values."""
        msg = {"role": MessageRole.USER, "content": "test"}
        assert msg["role"] == "user"
        assert msg["role"] == MessageRole.USER

    def test_consent_response_in_conditional(self):
        """Enum values should work in conditional checks."""
        response = ConsentResponse.YES
        if response == "y":
            passed = True
        else:
            passed = False
        assert passed

    def test_enum_string_methods(self):
        """Enum values should support string methods."""
        assert ProviderName.PERPLEXITY.upper() == "PERPLEXITY"
        assert SystemPromptMode.PREPEND.startswith("pre")
        assert len(ShellRiskLevel.DANGEROUS) == 9


class TestValidationHelpers:
    """Test validation helper functions."""

    def test_is_valid_provider_valid(self):
        """Valid provider names should return True."""
        assert is_valid_provider("perplexity")
        assert is_valid_provider("gemini")
        assert is_valid_provider("openai")

    def test_is_valid_provider_invalid(self):
        """Invalid provider names should return False."""
        assert not is_valid_provider("invalid")
        assert not is_valid_provider("")
        assert not is_valid_provider("Perplexity")  # Case sensitive

    def test_is_valid_role(self):
        """Test message role validation."""
        assert is_valid_role("user")
        assert is_valid_role("assistant")
        assert not is_valid_role("admin")

    def test_is_valid_consent_mode(self):
        """Test consent mode validation."""
        assert is_valid_consent_mode("always")
        assert is_valid_consent_mode("never")
        assert is_valid_consent_mode("prompt")
        assert not is_valid_consent_mode("sometimes")

    def test_is_valid_consent_response(self):
        """Test consent response validation."""
        assert is_valid_consent_response("y")
        assert is_valid_consent_response("n")
        assert is_valid_consent_response("always")
        assert is_valid_consent_response("never")
        assert not is_valid_consent_response("yes")  # Not "yes", it's "y"

    def test_is_valid_consent_decision(self):
        """Test consent decision validation."""
        assert is_valid_consent_decision("yes")
        assert is_valid_consent_decision("no")
        assert is_valid_consent_decision("always")
        assert is_valid_consent_decision("never")
        assert not is_valid_consent_decision("y")  # Not "y", it's "yes"

    def test_consent_decision_enum_values(self):
        """Test ConsentDecision enum values match expected strings."""
        assert ConsentDecision.YES == "yes"
        assert ConsentDecision.NO == "no"
        assert ConsentDecision.ALWAYS == "always"
        assert ConsentDecision.NEVER == "never"

    def test_consent_response_vs_decision(self):
        """Test that ConsentResponse and ConsentDecision have different YES/NO values."""
        # ConsentResponse uses short forms
        assert ConsentResponse.YES == "y"
        assert ConsentResponse.NO == "n"
        # ConsentDecision uses long forms
        assert ConsentDecision.YES == "yes"
        assert ConsentDecision.NO == "no"
        # ALWAYS and NEVER are the same in both
        assert ConsentResponse.ALWAYS == ConsentDecision.ALWAYS
        assert ConsentResponse.NEVER == ConsentDecision.NEVER

    def test_is_valid_prompt_mode(self):
        """Test system prompt mode validation."""
        assert is_valid_prompt_mode("prepend")
        assert is_valid_prompt_mode("append")
        assert is_valid_prompt_mode("replace")
        assert not is_valid_prompt_mode("insert")

    def test_is_valid_risk_level(self):
        """Test shell risk level validation."""
        assert is_valid_risk_level("safe")
        assert is_valid_risk_level("dangerous")
        assert is_valid_risk_level("never")
        assert not is_valid_risk_level("risky")

    def test_is_valid_encoding(self):
        """Test file encoding validation."""
        assert is_valid_encoding("utf-8")
        assert is_valid_encoding("utf-8-sig")
        assert not is_valid_encoding("ascii")

    def test_is_valid_checkpoint_backend(self):
        """Test checkpoint backend validation."""
        assert is_valid_checkpoint_backend("auto")
        assert is_valid_checkpoint_backend("git")
        assert is_valid_checkpoint_backend("file")
        assert is_valid_checkpoint_backend("none")
        assert not is_valid_checkpoint_backend("memory")


class TestGenericHelpers:
    """Test generic enum helper functions."""

    def test_is_valid_enum_generic(self):
        """Test generic is_valid_enum function."""
        assert is_valid_enum(ProviderName, "perplexity")
        assert not is_valid_enum(ProviderName, "invalid")

    def test_get_enum_values(self):
        """Test get_enum_values returns all values."""
        values = get_enum_values(ConsentResponse)
        assert values == {"y", "n", "always", "never"}

        provider_values = get_enum_values(ProviderName)
        assert "perplexity" in provider_values
        assert "gemini" in provider_values
        assert len(provider_values) == 5


class TestEnumMembership:
    """Test enum membership and iteration."""

    def test_enum_iteration(self):
        """Enums should be iterable."""
        providers = list(ProviderName)
        assert len(providers) == 5
        assert ProviderName.PERPLEXITY in providers

    def test_enum_membership_check(self):
        """Test membership check using 'in' operator."""
        # Note: 'in' checks enum members, not values
        assert ProviderName.PERPLEXITY in ProviderName
        # For value check, use validation helper
        assert is_valid_provider("perplexity")
