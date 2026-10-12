"""Application settings, loaded from environment variables / .env."""

from functools import lru_cache
from typing import Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

LLMProvider = Literal["azure_openai", "gemini"]
EmbeddingProvider = Literal["ollama", "gemini"]
LogFormat = Literal["text", "json"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # Postgres / PGVector
    database_url: str = Field(alias="DATABASE_URL")
    # Unprivileged role tenant sessions switch to, so RLS applies even when the connecting
    # role is a superuser or the table owner. Interpolated into SQL, hence the pattern.
    db_app_role: str = Field(
        default="ai_employee_app", alias="DB_APP_ROLE", pattern=r"^[a-z_][a-z0-9_]{0,62}$"
    )

    # Provider selection
    llm_provider: LLMProvider = Field(default="azure_openai", alias="LLM_PROVIDER")
    embedding_provider: EmbeddingProvider = Field(default="ollama", alias="EMBEDDING_PROVIDER")

    # Vector width. Must match the active embedding model, and is baked into the chunks
    # table when the schema is first applied - changing it later requires a migration.
    embedding_dim: int = Field(default=768, alias="EMBEDDING_DIM")

    # Ollama embeddings
    ollama_base_url: str = Field(default="http://localhost:11434", alias="OLLAMA_BASE_URL")
    embedding_model: str = Field(default="nomic-embed-text", alias="EMBEDDING_MODEL")

    # Azure OpenAI
    azure_openai_api_key: str = Field(default="", alias="AZURE_OPENAI_API_KEY")
    azure_openai_endpoint: str = Field(default="", alias="AZURE_OPENAI_ENDPOINT")
    azure_openai_deployment: str = Field(default="", alias="AZURE_OPENAI_DEPLOYMENT")
    azure_openai_api_version: str = Field(default="2024-10-21", alias="AZURE_OPENAI_API_VERSION")

    # Google Gemini
    google_api_key: str = Field(default="", alias="GOOGLE_API_KEY")
    gemini_chat_model: str = Field(default="gemini-2.5-flash", alias="GEMINI_CHAT_MODEL")
    gemini_embedding_model: str = Field(
        default="models/text-embedding-004", alias="GEMINI_EMBEDDING_MODEL"
    )
    # Left unset, the model's native width is used. Only set it for models that support
    # truncated output dimensions.
    gemini_embedding_output_dim: int | None = Field(
        default=None, alias="GEMINI_EMBEDDING_OUTPUT_DIM"
    )

    # Azure Blob Storage ingestion source. Either a connection string, or the account URL
    # with an Entra ID identity resolved by DefaultAzureCredential.
    azure_storage_connection_string: str = Field(
        default="", alias="AZURE_STORAGE_CONNECTION_STRING"
    )
    azure_storage_account_url: str = Field(default="", alias="AZURE_STORAGE_ACCOUNT_URL")

    # Signs the web session cookie. The default is only acceptable for local development.
    session_secret: str = Field(default="dev-insecure-session-secret", alias="SESSION_SECRET")

    # Applies to the ai_employee logger tree only; third-party loggers stay at WARNING.
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    log_format: LogFormat = Field(default="text", alias="LOG_FORMAT")


@lru_cache
def get_settings() -> Settings:
    """Cached accessor so the .env file is parsed once per process."""
    # Required fields are supplied from the environment, not by the caller.
    return Settings()  # type: ignore[call-arg]
