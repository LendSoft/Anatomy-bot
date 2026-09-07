"""Конфигурация приложения из переменных окружения.

Здесь только то, что задаётся при деплое и не меняется на лету.
Всё, что администратор крутит из панели (температура, top_k, пороги,
промпты), живёт в БД — см. app/services/settings_service.py.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# ollama — локальная модель на своём железе, gigachat — облачный резерв
LLMProvider = Literal["ollama", "gigachat"]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # ---------- общее ----------
    project_name: str = "Anatomy Bot"
    environment: Literal["development", "production"] = "development"
    log_level: str = "INFO"
    api_v1_prefix: str = "/api/v1"

    # ---------- Postgres ----------
    postgres_user: str = "anatomy"
    postgres_password: str = "anatomy"
    postgres_db: str = "anatomy"
    postgres_host: str = "postgres"
    postgres_port: int = 5432

    # ---------- Redis ----------
    redis_host: str = "redis"
    redis_port: int = 6379
    redis_db: int = 0

    # ---------- безопасность ----------
    secret_key: str = "insecure-dev-key-change-me"
    algorithm: str = "HS256"
    access_token_expire_minutes: int = 720
    first_admin_email: str = "admin@example.ru"
    first_admin_password: str = "admin"
    # Строкой, а не list[str]: для полей-контейнеров pydantic-settings
    # пытается разобрать значение как JSON ещё до валидаторов и падает
    # на обычном перечислении через запятую. Список отдаёт cors_origins.
    cors_origins_raw: str = Field(
        default="http://localhost:5173", validation_alias="CORS_ORIGINS"
    )

    # ---------- LLM ----------
    llm_provider: LLMProvider = "ollama"
    llm_model: str = "qwen3:8b"
    llm_base_url: str = "http://ollama:11434/v1"
    llm_api_key: str = "not-needed-for-local"
    llm_timeout_seconds: int = 180

    llm_fallback_enabled: bool = False
    llm_fallback_provider: LLMProvider | None = "gigachat"
    llm_fallback_model: str | None = "GigaChat-2"

    # ---------- GigaChat (резервный провайдер) ----------
    # Ключ авторизации из личного кабинета — строка base64, а не пара логин/пароль
    gigachat_auth_key: str | None = None
    gigachat_client_id: str | None = None
    gigachat_client_secret: str | None = None
    gigachat_scope: str = "GIGACHAT_API_PERS"
    gigachat_model: str = "GigaChat-2"
    # true | false | путь к PEM-файлу корневого сертификата НУЦ Минцифры
    gigachat_verify_ssl: str = "false"

    # ---------- эмбеддинги ----------
    embeddings_base_url: str = "http://embeddings:8100"
    embedding_model: str = "BAAI/bge-m3"
    embedding_dim: int = 1024
    reranker_model: str = "BAAI/bge-reranker-v2-m3"

    # ---------- хранилище ----------
    storage_dir: str = "/data/storage"
    max_upload_size_mb: int = 200

    # ---------- VK ----------
    vk_enabled: bool = False
    vk_group_token: str | None = None
    vk_group_id: str | None = None
    vk_rate_limit_per_minute: int = 10
    vk_api_version: str = "5.199"

    @field_validator("llm_fallback_provider", "llm_fallback_model",
                     "vk_group_token", "vk_group_id",
                     "gigachat_auth_key", "gigachat_client_id", "gigachat_client_secret",
                     mode="before")
    @classmethod
    def _empty_to_none(cls, v: object) -> object:
        """В compose незаполненные переменные приходят пустой строкой."""
        if isinstance(v, str) and not v.strip():
            return None
        return v

    @property
    def gigachat_verify(self) -> bool | str:
        """httpx принимает bool либо путь к сертификату — приводим строку из .env."""
        value = (self.gigachat_verify_ssl or "").strip()
        if value.lower() in ("false", "0", "no", ""):
            return False
        if value.lower() in ("true", "1", "yes"):
            return True
        return value  # путь к PEM-файлу

    @property
    def cors_origins(self) -> list[str]:
        """CORS_ORIGINS задаётся строкой через запятую."""
        return [item.strip() for item in self.cors_origins_raw.split(",") if item.strip()]

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+asyncpg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def redis_url(self) -> str:
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    @property
    def is_production(self) -> bool:
        return self.environment == "production"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
