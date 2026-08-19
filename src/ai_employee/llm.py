"""Chat model providers.

Adding a provider means writing a builder and a config check, then registering both.
Nothing outside this module names a vendor.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from functools import lru_cache

from langchain_core.language_models import BaseChatModel

from ai_employee.config import Settings, get_settings

logger = logging.getLogger(__name__)

# Grounded answers should not vary between runs, and the evaluation harness depends on
# repeatability.
TEMPERATURE = 0.0


class LLMNotConfiguredError(RuntimeError):
    """Raised when the selected chat provider is missing required settings."""


def _missing(settings: Settings, required: dict[str, str]) -> list[str]:
    return [name for name, attribute in required.items() if not getattr(settings, attribute)]


_AZURE_REQUIRED = {
    "AZURE_OPENAI_API_KEY": "azure_openai_api_key",
    "AZURE_OPENAI_ENDPOINT": "azure_openai_endpoint",
    "AZURE_OPENAI_DEPLOYMENT": "azure_openai_deployment",
}

_GEMINI_REQUIRED = {"GOOGLE_API_KEY": "google_api_key"}


def _build_azure(settings: Settings) -> BaseChatModel:
    from langchain_openai import AzureChatOpenAI

    return AzureChatOpenAI(
        azure_endpoint=settings.azure_openai_endpoint,
        api_key=settings.azure_openai_api_key,
        azure_deployment=settings.azure_openai_deployment,
        api_version=settings.azure_openai_api_version,
        temperature=TEMPERATURE,
    )


def _build_gemini(settings: Settings) -> BaseChatModel:
    from langchain_google_genai import ChatGoogleGenerativeAI

    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
        temperature=TEMPERATURE,
    )


# provider -> (builder, required settings, model-name attribute)
_PROVIDERS: dict[str, tuple[Callable[[Settings], BaseChatModel], dict[str, str], str]] = {
    "azure_openai": (_build_azure, _AZURE_REQUIRED, "azure_openai_deployment"),
    "gemini": (_build_gemini, _GEMINI_REQUIRED, "gemini_chat_model"),
}


def check_config() -> tuple[bool, str]:
    """Readiness of the selected chat provider, for the health endpoint."""
    settings = get_settings()
    build, required, model_attribute = _PROVIDERS[settings.llm_provider]
    missing = _missing(settings, required)
    if missing:
        return False, f"{settings.llm_provider}: missing {', '.join(missing)}"
    return True, f"{settings.llm_provider}: {getattr(settings, model_attribute)}"


@lru_cache
def get_chat_model() -> BaseChatModel:
    """The configured chat model. Cached; call get_settings.cache_clear() to re-read config."""
    settings = get_settings()
    build, required, _ = _PROVIDERS[settings.llm_provider]

    missing = _missing(settings, required)
    if missing:
        raise LLMNotConfiguredError(
            f"llm_provider={settings.llm_provider} requires: {', '.join(missing)}"
        )

    logger.info("chat provider: %s", settings.llm_provider)
    return build(settings)