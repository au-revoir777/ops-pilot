"""Unit tests for application configuration."""

import pytest
from pydantic import ValidationError

from app.config import Settings, assert_test_database_url, get_settings

PROD_URL = "postgresql+asyncpg://user:s3cret@db.internal:5432/opspilot"
TEST_URL = "postgresql+asyncpg://user:pw@localhost:5433/opspilot_test"


def make_settings(**overrides) -> Settings:
    # _env_file=None: unit tests must not depend on a developer's local .env
    return Settings(_env_file=None, **overrides)


class TestDefaults:
    def test_default_settings_load(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.delenv("APP_ENV", raising=False)
        settings = make_settings()
        assert settings.app_env == "development"
        assert settings.api_port == 8000
        assert settings.database_url is None

    def test_pool_defaults(self):
        settings = make_settings()
        assert settings.db_pool_size == 5
        assert settings.db_max_overflow == 10
        assert settings.db_pool_timeout == 30
        assert settings.db_pool_recycle == 1800
        assert settings.db_pool_pre_ping is True

    def test_pool_settings_from_env(self, monkeypatch):
        monkeypatch.setenv("DB_POOL_SIZE", "20")
        monkeypatch.setenv("DB_POOL_PRE_PING", "false")
        settings = make_settings()
        assert settings.db_pool_size == 20
        assert settings.db_pool_pre_ping is False

    def test_invalid_pool_size_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(db_pool_size=0)

    def test_rag_defaults(self):
        settings = make_settings()
        assert settings.rag_chunk_size == 512
        assert settings.rag_top_k == 5

    def test_get_settings_returns_cached(self):
        assert get_settings() is get_settings()


class TestEnvironments:
    @pytest.mark.parametrize("env", ["development", "test", "production"])
    def test_supported_environments(self, env):
        assert make_settings(app_env=env).app_env == env

    def test_unknown_environment_rejected(self):
        with pytest.raises(ValidationError):
            make_settings(app_env="staging-ish")

    def test_is_production(self):
        assert make_settings(app_env="production").is_production is True
        assert make_settings().is_production is False


class TestDatabaseUrlSafety:
    def test_url_is_secret_in_repr(self):
        settings = make_settings(database_url=PROD_URL)
        assert "s3cret" not in repr(settings)
        assert "s3cret" not in str(settings.model_dump())

    def test_require_database_url_when_missing(self, monkeypatch):
        monkeypatch.delenv("DATABASE_URL", raising=False)
        with pytest.raises(RuntimeError, match="DATABASE_URL is not configured"):
            make_settings().require_database_url()

    def test_test_env_refuses_non_test_database(self):
        with pytest.raises(ValidationError, match="_test"):
            make_settings(app_env="test", database_url=PROD_URL)

    def test_test_env_accepts_test_database(self):
        settings = make_settings(app_env="test", database_url=TEST_URL)
        assert settings.require_database_url() == TEST_URL

    def test_guard_error_does_not_leak_password(self):
        with pytest.raises(ValueError) as excinfo:
            assert_test_database_url(PROD_URL)
        assert "s3cret" not in str(excinfo.value)
