"""Unit tests for ppxai.config module."""
import pytest
from ppxai.config import (
    SESSIONS_DIR,
    EXPORTS_DIR,
    USAGE_FILE,
    MODEL_PRICING,
    MODELS,
    CODING_MODEL,
)


class TestConfig:
    """Tests for configuration constants."""

    def test_sessions_dir_exists(self):
        """Test that sessions directory is created."""
        assert SESSIONS_DIR.exists()
        assert SESSIONS_DIR.is_dir()

    def test_exports_dir_exists(self):
        """Test that exports directory is created."""
        assert EXPORTS_DIR.exists()
        assert EXPORTS_DIR.is_dir()

    def test_usage_file_path(self):
        """Test that usage file path is valid."""
        assert USAGE_FILE.name == "usage.json"
        assert USAGE_FILE.parent.name == ".ppxai"

    def test_model_pricing_structure(self):
        """Test that model pricing has correct structure."""
        assert len(MODEL_PRICING) > 0
        for model, pricing in MODEL_PRICING.items():
            assert "input" in pricing
            assert "output" in pricing
            assert isinstance(pricing["input"], (int, float))
            assert isinstance(pricing["output"], (int, float))
            assert pricing["input"] >= 0
            assert pricing["output"] >= 0

    def test_models_structure(self):
        """Test that models have correct structure."""
        assert len(MODELS) > 0
        for key, model in MODELS.items():
            assert "id" in model
            assert "name" in model
            assert "description" in model
            assert isinstance(model["id"], str)
            assert isinstance(model["name"], str)
            assert isinstance(model["description"], str)

    def test_coding_model_valid(self):
        """Test that coding model is a valid model ID."""
        model_ids = [m["id"] for m in MODELS.values()]
        assert CODING_MODEL in model_ids

    def test_all_models_have_pricing(self):
        """Test that all models have pricing defined."""
        for model in MODELS.values():
            assert model["id"] in MODEL_PRICING, f"No pricing for {model['id']}"
