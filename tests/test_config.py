"""Settings parsing and provider readiness."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from ai_employee import llm
from ai_employee.config import Settings, get_settings


class TestSettings:
    def test_values_are_read_from_the_aliased_variables(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("EMBEDDING_DIM", "1536")

        settings = Settings()

        assert settings.llm_provider == "gemini"
        assert settings.embedding_dim == 1536

    def test_an_unknown_provider_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "not-a-provider")

        # Catching this at startup beats a KeyError deep inside _PROVIDERS at request time.
        with pytest.raises(ValidationError):
            Settings()

    def test_an_unsafe_db_role_name_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("DB_APP_ROLE", 'app"; DROP ROLE x; --')

        with pytest.raises(ValidationError):
            Settings()  # type: ignore[call-arg]

    def test_unrelated_variables_are_ignored(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("SOME_UNRELATED_VARIABLE", "value")

        Settings()

    def test_settings_are_cached(self) -> None:
        assert get_settings() is get_settings()

    def test_the_cache_can_be_cleared(self, monkeypatch: pytest.MonkeyPatch) -> None:
        first = get_settings()
        monkeypatch.setenv("LOG_LEVEL", "DEBUG")
        get_settings.cache_clear()

        second = get_settings()

        assert second is not first
        assert second.log_level == "DEBUG"


class TestLLMCheckConfig:
    def test_gemini_is_ready_when_the_key_is_present(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GOOGLE_API_KEY", "key")
        monkeypatch.setenv("GEMINI_CHAT_MODEL", "gemini-2.5-flash")
        get_settings.cache_clear()

        ok, detail = llm.check_config()

        assert ok
        assert detail == "gemini: gemini-2.5-flash"

    def test_gemini_without_a_key_names_the_missing_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        get_settings.cache_clear()

        ok, detail = llm.check_config()

        assert not ok
        assert "GOOGLE_API_KEY" in detail

    def test_azure_reports_every_missing_variable_at_once(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
        for name in ("AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT", "AZURE_OPENAI_DEPLOYMENT"):
            monkeypatch.setenv(name, "")
        get_settings.cache_clear()

        ok, detail = llm.check_config()

        assert not ok
        # One health check should name all three, not send the operator round three times.
        assert "AZURE_OPENAI_API_KEY" in detail
        assert "AZURE_OPENAI_ENDPOINT" in detail
        assert "AZURE_OPENAI_DEPLOYMENT" in detail

    def test_azure_is_ready_when_fully_configured(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "azure_openai")
        monkeypatch.setenv("AZURE_OPENAI_API_KEY", "key")
        monkeypatch.setenv("AZURE_OPENAI_ENDPOINT", "https://example.openai.azure.com")
        monkeypatch.setenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")
        get_settings.cache_clear()

        ok, detail = llm.check_config()

        assert ok
        assert detail == "azure_openai: gpt-4o"

    def test_an_unconfigured_provider_raises_rather_than_returning_a_broken_model(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("LLM_PROVIDER", "gemini")
        monkeypatch.setenv("GOOGLE_API_KEY", "")
        get_settings.cache_clear()
        llm.get_chat_model.cache_clear()

        with pytest.raises(llm.LLMNotConfiguredError, match="GOOGLE_API_KEY"):
            llm.get_chat_model()

        llm.get_chat_model.cache_clear()
