"""Резервный провайдер — GigaChat (Сбер).

Два отличия от обычного OpenAI-совместимого API, из-за которых нужен
отдельный клиент:

1. Авторизация двухступенчатая. Постоянный ключ обменивается на access token
   со сроком жизни 30 минут, дальше запросы идут с ним. Токен обновляется
   здесь автоматически.
2. Сертификат сервера подписан НУЦ Минцифры. В типовой Linux-образ этот
   корневой сертификат не входит, поэтому проверку TLS нужно либо настроить
   (см. deploy/install-russian-ca.sh), либо явно отключить.

Модели: GigaChat-2, GigaChat-2-Pro, GigaChat-2-Max.
"""

from __future__ import annotations

import asyncio
import base64
import json
import time
import uuid
from collections.abc import AsyncIterator

import httpx
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.logging import get_logger
from app.llm.base import BaseLLM, ChatMessage, GenerationParams, LLMError, LLMResponse

log = get_logger(__name__)

OAUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
API_BASE_URL = "https://gigachat.devices.sberbank.ru/api/v1"

# Обновляем токен заранее: иначе длинный запрос может начаться на живом
# токене и закончиться на протухшем
TOKEN_REFRESH_MARGIN_SECONDS = 120

# GigaChat отклоняет temperature = 0, минимально допустимое значение выше нуля.
# Промпт судьи задаёт нулевую температуру ради воспроизводимости — подменяем
# её на минимально возможную, а не роняем запрос.
MIN_TEMPERATURE = 0.01


class GigaChatLLM(BaseLLM):
    provider_name = "gigachat"

    def __init__(
        self,
        model: str = "GigaChat-2",
        auth_key: str | None = None,
        scope: str = "GIGACHAT_API_PERS",
        client_id: str | None = None,
        client_secret: str | None = None,
        verify_ssl: bool | str = False,
        timeout: int = 180,
    ) -> None:
        super().__init__(model)
        self.scope = scope

        # Ключ авторизации из личного кабинета — это уже base64(client_id:secret).
        # Если по какой-то причине его нет, собираем сами из пары значений.
        if auth_key:
            self.auth_key = auth_key
        elif client_id and client_secret:
            self.auth_key = base64.b64encode(
                f"{client_id}:{client_secret}".encode()
            ).decode()
        else:
            self.auth_key = ""

        self._access_token: str | None = None
        self._expires_at: float = 0.0
        self._token_lock = asyncio.Lock()

        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(timeout, connect=15.0),
            verify=verify_ssl,
        )

    # ------------------------------------------------------------ авторизация

    async def _ensure_token(self) -> str:
        if not self.auth_key:
            raise LLMError(
                "Не задан ключ авторизации GigaChat (переменная GIGACHAT_AUTH_KEY)"
            )

        if self._access_token and time.time() < self._expires_at:
            return self._access_token

        # Под блокировкой, чтобы параллельные запросы не обновляли токен наперегонки
        async with self._token_lock:
            if self._access_token and time.time() < self._expires_at:
                return self._access_token

            try:
                response = await self._client.post(
                    OAUTH_URL,
                    headers={
                        "Authorization": f"Basic {self.auth_key}",
                        "RqUID": str(uuid.uuid4()),
                        "Content-Type": "application/x-www-form-urlencoded",
                        "Accept": "application/json",
                    },
                    data={"scope": self.scope},
                )
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                body = exc.response.text[:300]
                log.error("gigachat_auth_failed", status=exc.response.status_code, body=body)
                raise LLMError(
                    f"GigaChat не выдал токен ({exc.response.status_code}): {body}"
                ) from exc
            except httpx.HTTPError as exc:
                raise LLMError(f"Нет связи с сервером авторизации GigaChat: {exc}") from exc

            data = response.json()
            self._access_token = data["access_token"]
            # expires_at приходит в миллисекундах
            self._expires_at = data["expires_at"] / 1000 - TOKEN_REFRESH_MARGIN_SECONDS

            log.info("gigachat_token_refreshed", scope=self.scope)
            return self._access_token

    # -------------------------------------------------------------- генерация

    def _payload(
        self, messages: list[ChatMessage], params: GenerationParams, stream: bool
    ) -> dict:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": max(params.temperature, MIN_TEMPERATURE),
            "top_p": params.top_p,
            "max_tokens": params.max_tokens,
            "stream": stream,
        }
        if params.stop:
            payload["stop"] = params.stop
        return payload

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ReadTimeout)),
        reraise=True,
    )
    async def chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> LLMResponse:
        token = await self._ensure_token()

        try:
            response = await self._client.post(
                f"{API_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json=self._payload(messages, params, stream=False),
            )
            if response.status_code == 401:
                # Токен отозвали раньше срока — берём новый и пробуем ещё раз
                self._access_token = None
                token = await self._ensure_token()
                response = await self._client.post(
                    f"{API_BASE_URL}/chat/completions",
                    headers={"Authorization": f"Bearer {token}"},
                    json=self._payload(messages, params, stream=False),
                )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            body = exc.response.text[:500]
            log.error("gigachat_http_error", status=exc.response.status_code, body=body)
            raise LLMError(f"GigaChat вернул {exc.response.status_code}: {body}") from exc
        except httpx.HTTPError as exc:
            log.error("gigachat_transport_error", error=str(exc))
            raise LLMError(f"Не удалось обратиться к GigaChat: {exc}") from exc

        data = response.json()
        choice = data["choices"][0]
        usage = data.get("usage") or {}

        finish_reason = choice.get("finish_reason")
        if finish_reason == "blacklist":
            raise LLMError("GigaChat отклонил запрос: тема попала под ограничения модели")

        return LLMResponse(
            content=choice["message"].get("content") or "",
            model=data.get("model", self.model),
            provider=self.provider_name,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            finish_reason=finish_reason,
        )

    async def stream_chat(
        self, messages: list[ChatMessage], params: GenerationParams
    ) -> AsyncIterator[str]:
        token = await self._ensure_token()

        try:
            async with self._client.stream(
                "POST",
                f"{API_BASE_URL}/chat/completions",
                headers={"Authorization": f"Bearer {token}"},
                json=self._payload(messages, params, stream=True),
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line.startswith("data: "):
                        continue
                    chunk = line[6:]
                    if chunk.strip() == "[DONE]":
                        break
                    try:
                        delta = json.loads(chunk)["choices"][0].get("delta", {})
                    except (json.JSONDecodeError, KeyError, IndexError):
                        continue
                    if content := delta.get("content"):
                        yield content
        except httpx.HTTPError as exc:
            raise LLMError(f"Ошибка потоковой генерации GigaChat: {exc}") from exc

    async def health(self) -> bool:
        try:
            token = await self._ensure_token()
            response = await self._client.get(
                f"{API_BASE_URL}/models",
                headers={"Authorization": f"Bearer {token}"},
                timeout=15.0,
            )
            return response.status_code == 200
        except (httpx.HTTPError, LLMError):
            return False

    async def close(self) -> None:
        await self._client.aclose()
