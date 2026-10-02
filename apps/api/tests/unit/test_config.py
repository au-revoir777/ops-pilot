"""Unit tests for application configuration."""

import pytest

from app.config import Settings, get_settings


@pytest.mark.unit
class TestSettings:
    """Tests for the Settings configuration class."""

    def test_default_settings_load(self):
        settings = Settings()
        assert settings.app_env == "development"
        assert settings.api_port == 8000
        assert settings.agent_max_steps == 15

    def test_is_production_false_by_default(self):
        settings = Settings()
        assert settings.is_production is False

    def test_is_production_true(self):
        settings = Settings(app_env="production")
        assert settings.is_production is True

    def test_rag_defaults(self):
        settings = Settings()
        assert settings.rag_chunk_size == 512
        assert settings.rag_chunk_overlap == 50
        assert settings.rag_top_k == 5
        assert settings.rag_similarity_threshold == 0.7

    def test_get_settings_returns_cached(self):
        s1 = get_settings()
        s2 = get_settings()
        assert s1 is s2
