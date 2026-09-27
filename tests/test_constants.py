"""Tests for constants module - enum behavior."""


from ppxai.constants import (
    ConsentDecision,
    ConsentResponse,
    MessageRole,
    ProviderName,
    ShellRiskLevel,
    SystemPromptMode,
)


class TestStrEnumBehavior:
    """Test that str, Enum classes behave correctly."""

    def test_provider_name_string_comparison(self):
        """Enum values should compare equal to their string values."""
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
        assert ProviderName.GEMINI.upper() == "GEMINI"
        assert SystemPromptMode.PREPEND.startswith("pre")
        assert len(ShellRiskLevel.DANGEROUS) == 9


class TestConsentEnums:
    """ConsentResponse (short forms) and ConsentDecision (long forms)."""

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


class TestEnumMembership:
    """Test enum membership and iteration."""

    def test_enum_iteration(self):
        """Enums should be iterable."""
        providers = list(ProviderName)
        assert len(providers) == 4
        assert ProviderName.GEMINI in providers

    def test_enum_membership_check(self):
        """Test membership check using 'in' operator."""
        # Note: 'in' checks enum members, not values
        assert ProviderName.GEMINI in ProviderName
        assert "gemini" in {p.value for p in ProviderName}
