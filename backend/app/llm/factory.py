"""Создание и кэширование клиентов языковых моделей.

Три провайдера:
  * vllm     — локальная модель на своём GPU, основной путь;
  * ollama   — альтернатива для машины без GPU или для быстрой пробы модели;
  * gigachat — облачный резерв, когда локальная модель недоступна.

vLLM и Ollama говорят на одном протоколе (OpenAI-совместимый
`/v1/chat/completions`), поэтому используют общий клиент и различаются
только адресом.

Клиенты держат пул HTTP-соединений, поэтому создаются один раз на процесс.
Ключ кэша включает параметры подключения: смена модели из админки
подхватывается без перезапуска контейнера.
"""

from __future__ import annotations

from app.core.config import settings
from app.core.logging import get_logger
from app.llm.base import BaseLLM
from app.llm.gigachat_client import GigaChatLLM
from app.llm.openai_compatible import OpenAICompatibleLLM

log = get_logger(__name__)

_cache: dict[tuple, BaseLLM] = {}

# Адрес по умолчанию для каждого локального провайдера. У Ollama
# OpenAI-совместимый слой живёт на /v1, как и у vLLM.
_DEFAULT_BASE_URLS = {
    "vllm": "http://llm:8000/v1",
    "ollama": "http://ollama:11434/v1",
}


def get_llm(
    provider: str | None = None,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    scope: str | None = None,
) -> BaseLLM:
    provider = provider or settings.llm_provider

    if provider == "gigachat":
        # Адрес у GigaChat фиксированный, а ключ и тип доступа приходят либо
        # из админ-панели, либо из переменных окружения сервера
        model = model or settings.gigachat_model
        auth_key = api_key or settings.gigachat_auth_key or ""
        scope = scope or settings.gigachat_scope
        key = ("gigachat", model, auth_key, scope)

        if key not in _cache:
            _cache[key] = GigaChatLLM(
                model=model,
                auth_key=auth_key or None,
                client_id=settings.gigachat_client_id,
                client_secret=settings.gigachat_client_secret,
                scope=scope,
                verify_ssl=settings.gigachat_verify,
                timeout=settings.llm_timeout_seconds,
            )
            log.info("llm_client_created", provider=provider, model=model)
        return _cache[key]

    if provider not in _DEFAULT_BASE_URLS:
        raise ValueError(
            f"Неизвестный провайдер LLM: {provider}. Доступны: vllm, ollama, gigachat"
        )

    model = model or settings.llm_model
    # Адрес из настроек берём только для основного провайдера: если выбран
    # другой, LLM_BASE_URL указывает не туда, и нужен адрес по умолчанию
    if not base_url:
        base_url = (
            settings.llm_base_url
            if provider == settings.llm_provider and settings.llm_base_url
            else _DEFAULT_BASE_URLS[provider]
        )
    api_key = api_key or settings.llm_api_key
    key = (provider, model, base_url)

    if key not in _cache:
        _cache[key] = OpenAICompatibleLLM(
            model=model,
            base_url=base_url,
            api_key=api_key,
            timeout=settings.llm_timeout_seconds,
            provider_name=provider,
        )
        log.info("llm_client_created", provider=provider, model=model, base_url=base_url)
    return _cache[key]


def get_fallback_llm(
    api_key: str | None = None,
    model: str | None = None,
    scope: str | None = None,
) -> BaseLLM | None:
    """Резервный провайдер, если он настроен и включён.

    Ключ и модель могут прийти из админ-панели — тогда они важнее того,
    что записано в переменных окружения сервера.
    """
    if not settings.llm_fallback_enabled or not settings.llm_fallback_provider:
        return None
    return get_llm(
        provider=settings.llm_fallback_provider,
        model=model or settings.llm_fallback_model,
        api_key=api_key,
        scope=scope,
    )


async def close_all() -> None:
    """Закрыть HTTP-сессии при остановке приложения."""
    for client in _cache.values():
        await client.close()
    _cache.clear()
